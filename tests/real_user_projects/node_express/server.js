const scenario = process.argv[2] || process.env.GHOSTFIX_SCENARIO || "missing-module";

function missingModule() {
  require("express-session-does-not-exist");
}

function badEnv() {
  if (!process.env.NODE_EXPRESS_API_KEY) {
    throw new Error("NODE_EXPRESS_API_KEY is required before server startup");
  }
}

function startupCrash() {
  throw new Error("Express startup failed while loading product routes");
}

if (scenario === "missing-module") {
  missingModule();
} else if (scenario === "bad-env") {
  badEnv();
} else if (scenario === "startup-crash") {
  startupCrash();
} else {
  throw new Error(`Unknown Node fixture scenario: ${scenario}`);
}
