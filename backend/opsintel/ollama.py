import httpx


class OllamaUnavailable(RuntimeError):
    pass


def parse_version(v: str) -> tuple[int, ...]:
    nums = []
    for part in v.split("-")[0].split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    return tuple(nums)


async def status(base_url: str, model: str, min_version: str, timeout: float = 2.0) -> dict:
    """Probe Ollama without loading the model."""
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            version = (await client.get("/api/version")).raise_for_status().json().get("version", "")
            tags = (await client.get("/api/tags")).raise_for_status().json().get("models", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}
    names = {m.get("name") for m in tags} | {m.get("model") for m in tags}
    model_present = model in names or f"{model}:latest" in names
    return {
        "reachable": True,
        "version": version,
        "version_ok": parse_version(version) >= parse_version(min_version),
        "model": model,
        "model_present": model_present,
    }
