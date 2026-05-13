class ORMQueryConstructionError(Exception):
    pass


class QuerySet:
    allowed_filters = {"email", "is_active"}

    def filter(self, **kwargs):
        invalid = set(kwargs) - self.allowed_filters
        if invalid:
            raise ORMQueryConstructionError(f"unknown ORM filter field: {sorted(invalid)[0]}")
        return []


users = QuerySet()
print(users.filter(profile__company_id=7))
