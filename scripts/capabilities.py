"""Explicit account model-list check; never submits an inference request."""
import httpx

from packages.common.config import settings


def main():
    cfg = settings()
    if not cfg.model_api_key:
        raise SystemExit("MODEL_API_KEY is absent. Set it in local .env when ready for the later live phase.")
    response = httpx.get(cfg.meta_base_url.rstrip("/") + "/models",
                         headers={"Authorization": f"Bearer {cfg.model_api_key}"}, timeout=30)
    response.raise_for_status()
    ids = {m["id"] for m in response.json().get("data", [])}
    for name in (cfg.muse_model, cfg.sam_model):
        print(name, "listed" if name in ids else "not listed; confirm provider model identifier/account access")
    print("No inference was requested. A listed model does not establish video input compatibility.")


if __name__ == "__main__":
    main()
