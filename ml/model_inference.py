"""
GhostFix AI - Local Model Inference Engine
Supports quantized models for efficient local inference
"""
import os
import json
import pickle
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

# Try to import torch, but allow running without it
try:
    import torch
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        pipeline,
    )
    TORCH_AVAILABLE = True
except Exception as e:
    TORCH_AVAILABLE = False
    print(f"⚠️  PyTorch not available: {e}")
    print("   Running in lightweight mode (retriever only)")


# Paths
MODEL_DIR = Path("ml/models")
VECTORIZER_PATH = MODEL_DIR / "vectorizer_v2.pkl"
RETRIEVER_PATH = MODEL_DIR / "retriever_v2.pkl"
RECORDS_PATH = MODEL_DIR / "retriever_records_v2.json"
LORA_PATH = MODEL_DIR / "ghostfix_lora"
BASE_MODEL = "microsoft/phi-2"


@dataclass
class InferenceConfig:
    """Configuration for model inference"""
    model_name: str = BASE_MODEL
    use_quantization: bool = True
    use_lora: bool = True
    max_new_tokens: int = 256
    temperature: float = 0.3
    top_p: float = 0.9
    top_k: int = 50
    device: str = "auto"
    retriever_top_k: int = 3


class LocalModelInference:
    """Local model inference with retrieval augmentation"""
    
    def __init__(self, config: Optional[InferenceConfig] = None):
        self.config = config or InferenceConfig()
        self.vectorizer = None
        self.retriever = None
        self.model = None
        self.tokenizer = None
        self.pipeline = None
        self._initialized = False
        self._retriever_only = not TORCH_AVAILABLE
    
    def _load_retriever(self):
        """Load TF-IDF retriever"""
        print("📂 Loading retriever model...")
        
        if not VECTORIZER_PATH.exists() or not RETRIEVER_PATH.exists():
            raise FileNotFoundError("Retriever artifacts are missing")

        with open(VECTORIZER_PATH, 'rb') as f:
            self.vectorizer = pickle.load(f)
        
        with open(RETRIEVER_PATH, 'rb') as f:
            self.retriever = pickle.load(f)
        
        print("   Retriever loaded successfully")
    
    def _load_base_model(self):
        """Load base language model with optional quantization"""
        if not TORCH_AVAILABLE:
            print("⚠️  PyTorch not available, skipping model loading")
            return
            
        print(f"📂 Loading base model: {self.config.model_name}...")
        
        quantization_config = None
        if self.config.use_quantization:
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4"
            )
            print("   Using 4-bit quantization")
        
        device_map = self.config.device
        
        self.model = AutoModelForCausalLM.from_pretrained(
            self.config.model_name,
            quantization_config=quantization_config,
            device_map=device_map,
            trust_remote_code=True,
            torch_dtype=torch.float16 if not self.config.use_quantization else None,
        )
        
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.config.model_name,
            trust_remote_code=True
        )
        
        # Set padding token
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        
        print("   Base model loaded successfully")
    
    def _load_lora(self):
        """Load LoRA adapter if available"""
        if LORA_PATH.exists() and self.config.use_lora:
            print("📂 Loading LoRA adapter...")
            from peft import PeftModel
            
            self.model = PeftModel.from_pretrained(
                self.model,
                str(LORA_PATH),
                device_map=self.config.device
            )
            print("   LoRA adapter loaded successfully")
    
    def _setup_pipeline(self):
        """Setup text generation pipeline"""
        self.pipeline = pipeline(
            "text-generation",
            model=self.model,
            tokenizer=self.tokenizer,
            max_new_tokens=self.config.max_new_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            top_k=self.config.top_k,
            do_sample=True,
            pad_token_id=self.tokenizer.pad_token_id,
        )
    
    def initialize(self):
        """Initialize all components"""
        if self._initialized:
            return
        
        print("\n" + "=" * 50)
        print("🚀 Initializing GhostFix Inference Engine")
        print("=" * 50)
        
        # Load retriever (always needed)
        self._load_retriever()
        
        if TORCH_AVAILABLE:
            # Load base model
            self._load_base_model()
            
            # Load LoRA if available
            self._load_lora()
            
            # Setup pipeline
            self._setup_pipeline()
        else:
            print("⚠️  Running in retriever-only mode (no LLM)")
        
        self._initialized = True
        print("\n✅ Initialization complete!")
    
    def retrieve_context(self, error_message: str, context: str = "") -> List[Dict]:
        """Retrieve relevant error records from memory"""
        if self.vectorizer is None or self.retriever is None:
            self._load_retriever()

        query = f"Error: {error_message}\nContext: {context}"
        
        X = self.vectorizer.transform([query])
        distances, indices = self.retriever.kneighbors(
            X, 
            n_neighbors=self.config.retriever_top_k
        )
        
        results = []
        for i, idx in enumerate(indices[0]):
            results.append({
                "index": int(idx),
                "distance": float(distances[0][i]),
            })
        
        return results

    def retrieve_records(self, error_message: str, context: str = "", top_k: Optional[int] = None) -> List[Dict]:
        """Retrieve complete local training records for evidence-aware prompting."""
        if self.vectorizer is None or self.retriever is None:
            self._load_retriever()

        if not RECORDS_PATH.exists():
            return []

        with open(RECORDS_PATH, "r", encoding="utf-8") as f:
            records = json.load(f)

        query = f"Error: {error_message}\nContext: {context}"
        X = self.vectorizer.transform([query])
        k = min(top_k or self.config.retriever_top_k, len(records))
        distances, indices = self.retriever.kneighbors(X, n_neighbors=k)

        results = []
        for distance, idx in zip(distances[0], indices[0]):
            record = dict(records[int(idx)])
            record["distance"] = float(distance)
            record["confidence"] = round((1 - float(distance)) * 100, 2)
            results.append(record)
        return results
    
    def build_prompt(self, error_message: str, context: str = "", retrieved: List[Dict] = None) -> str:
        """Build prompt for the model"""
        # Start with system prompt
        prompt = """You are GhostFix, an expert Python debugging assistant. 
Analyze the error and provide a clear explanation and fix.

"""
        
        # Add retrieved examples if available
        if retrieved:
            prompt += "Similar errors and their solutions:\n"
            for i, r in enumerate(retrieved[:2], 1):
                prompt += f"\nExample {i}:\n"
                prompt += f"Error: {r.get('error', '')}\n"
                prompt += f"Cause: {r.get('cause', '')}\n"
                prompt += f"Fix: {r.get('fix', '')}\n"
        
        # Add current error
        prompt += f"\n{'='*50}\n"
        prompt += f"Current Error:\n{error_message}\n"
        
        if context:
            prompt += f"\nContext:\n{context}\n"
        
        prompt += """
{'='*50}
Analysis:
1. Root Cause:
2. Explanation:
3. Fix:
"""
        
        return prompt
    
    def generate_fix(
        self, 
        error_message: str, 
        context: str = "",
        use_retrieval: bool = True
    ) -> Dict[str, str]:
        """Generate fix for the given error"""
        if not self._initialized:
            self.initialize()
        
        # Retrieve similar errors
        retrieved = None
        if use_retrieval:
            retrieved = self.retrieve_context(error_message, context)
        
        # If no LLM available, return retriever results only
        if not TORCH_AVAILABLE or self._retriever_only:
            return {
                "error": error_message,
                "context": context,
                "retrieved": retrieved,
                "mode": "retriever_only"
            }
        
        # Build prompt
        prompt = self.build_prompt(error_message, context, retrieved)
        
        # Generate response
        outputs = self.pipeline(prompt)
        response = outputs[0]["generated_text"]
        
        # Parse response
        result = {
            "error": error_message,
            "context": context,
            "prompt": prompt,
            "response": response,
            "retrieved": retrieved,
        }
        
        # Try to extract structured info
        try:
            lines = response.split("\n")
            current_section = None
            for line in lines:
                line = line.strip()
                if line.startswith("1. Root Cause:"):
                    current_section = "cause"
                    result["cause"] = line.replace("1. Root Cause:", "").strip()
                elif line.startswith("2. Explanation:"):
                    current_section = "explanation"
                    result["explanation"] = line.replace("2. Explanation:", "").strip()
                elif line.startswith("3. Fix:"):
                    current_section = "fix"
                    result["fix"] = line.replace("3. Fix:", "").strip()
                elif current_section and line:
                    result[current_section] += " " + line
        except Exception:
            pass
        
        return result
    
    def quick_lookup(self, error_message: str) -> Optional[Dict]:
        """Quick lookup using only retriever (no LLM)"""
        if self.vectorizer is None or self.retriever is None:
            self._load_retriever()
        
        query = f"Error: {error_message}"
        X = self.vectorizer.transform([query])
        distances, indices = self.retriever.kneighbors(X, n_neighbors=1)
        
        if distances[0][0] < 0.5:  # Threshold for confidence
            return {
                "index": int(indices[0][0]),
                "distance": float(distances[0][0]),
            }
        
        return None
    
    def cleanup(self):
        """Cleanup resources"""
        if self.model:
            del self.model
        if self.tokenizer:
            del self.tokenizer
        if self.pipeline:
            del self.pipeline
        
        if TORCH_AVAILABLE:
            torch.cuda.empty_cache() if torch.cuda.is_available() else None
        
        self._initialized = False
        print("🧹 Resources cleaned up")


# Singleton instance
_inference_engine: Optional[LocalModelInference] = None


def get_inference_engine(config: Optional[InferenceConfig] = None) -> LocalModelInference:
    """Get or create inference engine singleton"""
    global _inference_engine
    
    if _inference_engine is None:
        _inference_engine = LocalModelInference(config)
    
    return _inference_engine


def generate_fix(
    error_message: str, 
    context: str = "",
    use_llm: bool = True,
    use_quantization: bool = True
) -> Dict[str, str]:
    """Convenience function to generate fix"""
    config = InferenceConfig(
        use_quantization=use_quantization,
        use_lora=use_llm,
    )
    
    engine = get_inference_engine(config)
    
    if use_llm:
        return engine.generate_fix(error_message, context)
    else:
        # Quick lookup only
        result = engine.quick_lookup(error_message)
        if result:
            return {"retrieved": result}
        return {"error": "No similar error found in memory"}


def _extract_section(text: str, section: str) -> str:
    marker = f"{section}:"
    if marker not in text:
        return ""
    after = text.split(marker, 1)[1]
    for stop in ("ROOT_CAUSE:", "FIX:", "PATCH_PLAN:", "CONFIDENCE:"):
        if stop != marker and stop in after:
            after = after.split(stop, 1)[0]
    return after.strip()


def analyze_debug_case(traceback_text: str, context: str = "", evidence_prompt: str = "") -> Dict[str, object]:
    """Analyze an error with local LoRA when available, otherwise retriever fallback.

    GhostFix must never crash just because optional ML dependencies or artifacts
    are missing, so every stage degrades to a low-confidence local response.
    """
    result: Dict[str, object] = {
        "mode": "low_confidence",
        "cause": "",
        "fix": "",
        "patch_plan": "",
        "confidence": 20,
        "retrieved_records": [],
    }

    try:
        engine = get_inference_engine()
        retrieved = engine.retrieve_records(traceback_text, context, top_k=engine.config.retriever_top_k)
        result["retrieved_records"] = retrieved
        if retrieved:
            best = retrieved[0]
            result.update({
                "mode": "retriever",
                "cause": best.get("cause", ""),
                "fix": best.get("fix", ""),
                "patch_plan": "Use similar local fixes as supporting evidence; validate any patch before applying.",
                "confidence": int(float(best.get("confidence", 50))),
            })
    except Exception as exc:
        result["retriever_error"] = str(exc)

    if not TORCH_AVAILABLE or not LORA_PATH.exists():
        if not result.get("cause"):
            result["cause"] = "Low confidence: needs manual review."
            result["fix"] = "Review traceback and local code context before editing."
        result["mode"] = result["mode"] if result["mode"] != "low_confidence" else "retriever_only"
        return result

    try:
        engine = get_inference_engine()
        if not engine._initialized:
            engine.initialize()
        if engine.pipeline is None:
            return result

        prompt = evidence_prompt or engine.build_prompt(traceback_text, context, result.get("retrieved_records") or [])
        outputs = engine.pipeline(prompt)
        response = outputs[0]["generated_text"]
        cause = _extract_section(response, "ROOT_CAUSE")
        fix = _extract_section(response, "FIX")
        patch_plan = _extract_section(response, "PATCH_PLAN")
        confidence_text = _extract_section(response, "CONFIDENCE")
        if cause or fix:
            result.update({
                "mode": "local_lora" if LORA_PATH.exists() else "local_llm",
                "cause": cause or result.get("cause", ""),
                "fix": fix or result.get("fix", ""),
                "patch_plan": patch_plan or result.get("patch_plan", ""),
                "response": response,
            })
            confidence_match = re.search(r"\d+", confidence_text or "")
            if confidence_match:
                result["confidence"] = int(confidence_match.group(0))
    except Exception as exc:
        result["llm_error"] = str(exc)

    if not result.get("cause"):
        result["cause"] = "Low confidence: needs manual review."
    if not result.get("fix"):
        result["fix"] = "Review traceback and local code context before editing."
    return result


if __name__ == "__main__":
    # Test the inference engine
    print("🧪 Testing GhostFix Inference Engine...")
    
    engine = LocalModelInference()
    
    # Test quick lookup
    test_error = "NameError: name 'foo' is not defined"
    result = engine.quick_lookup(test_error)
    print(f"\nQuick lookup result: {result}")
    
    # Test full generation (if model is available)
    # result = engine.generate_fix(test_error, "def bar(): return foo")
    # print(f"\nFull generation result: {result}")
    
    print("\n✅ Test complete!")
