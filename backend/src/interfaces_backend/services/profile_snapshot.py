from typing import Optional


def extract_profile_name(profile_snapshot: Optional[dict]) -> Optional[str]:
    if not isinstance(profile_snapshot, dict):
        return None
    name = profile_snapshot.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    profile = profile_snapshot.get("profile")
    if isinstance(profile, dict):
        nested_name = profile.get("name")
        if isinstance(nested_name, str) and nested_name.strip():
            return nested_name.strip()
    return None
