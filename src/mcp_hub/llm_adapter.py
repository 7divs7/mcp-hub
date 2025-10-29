import os
import yaml
from openai import OpenAI
from anthropic import Anthropic
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

project_root = Path(os.getenv("PROJECT_ROOT")).resolve()
MODEL_CONFIG_PATH = project_root / "models_config.yaml"

class LLMAdapter:
    def __init__(self, provider: str = None, model: str = None, config_path=MODEL_CONFIG_PATH):
        # Use default model if not specified
        self.provider = provider.lower() or "huggingface"
        self.model = model or "gpt-oss-120b"

        # Load model configurations
        with open(config_path, "r") as f:
            supported_models = yaml.safe_load(f)

        if self.provider not in supported_models:
            raise ValueError(f"Unsupported provider: {provider}")
        
        print(self.provider, self.model)

        model_info = supported_models[self.provider][self.model]
        self.model_id = model_info["model_id"]
        self.base_url = os.path.expandvars(model_info["base_url"]) if model_info["base_url"] else None
        self.api_key = os.getenv(model_info["api_env"])


        # Initialize the appropriate client
        if self.provider == "anthropic":
            self.client = Anthropic(api_key=self.api_key)
        else:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)


    def chat(self, messages, **kwargs):
        if self.provider in ["openai", "huggingface", "databricks"]:
            return self.client.chat.completions.create(model=self.model,
                                                       messages=messages,
                                                       **kwargs)
        elif self.provider == "anthropic":
            # convert messages to Anthropic’s expected prompt format
            text = "\n".join([f"{m['role']}: {m['content']}" for m in messages])
            response = self.client.messages.create(model=self.model, messages=text)
            return response
