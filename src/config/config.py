"""
Configuration module for the AI agent laboratory.

This code was developed with the assistance of Claude Code.
"""
import os
from pathlib import Path
import re
import yaml
from urllib.parse import urlsplit
from typing import Dict, List, Optional, Any
from ..llm_client import BASE_URLS, RESERVED_BODY_FIELDS, SUPPORTED_PROVIDERS


class LabConfig:
    """Configuration for the AI agent laboratory."""

    def __init__(self, config_path: str):
        """
        Initialize configuration from a YAML file.

        Args:
            config_path: Path to the configuration YAML file.
        """
        self.config_path = config_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")

        # Credentials belong in an untracked .env file.  Keep this loader
        # dependency-free and never overwrite variables supplied by the shell.
        self._load_dotenv(Path(self.config_path).resolve().parent / '.env')
        
        try:
            with open(self.config_path, 'r', encoding='utf-8-sig') as file:
                config = yaml.safe_load(file)
        except yaml.YAMLError:
            # YAML exceptions may include the offending line, which can be a key.
            raise ValueError("Invalid YAML. Check indentation and quotes in config.yaml.") from None
        
        self._validate_config(config)
        return config

    @staticmethod
    def _load_dotenv(dotenv_path: Path) -> None:
        """Load simple KEY=VALUE pairs without printing or persisting secrets."""
        if not dotenv_path.exists():
            return
        try:
            lines = dotenv_path.read_text(encoding='utf-8').splitlines()
        except OSError:
            return
        assignment = re.compile(r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            match = assignment.match(line)
            if not match:
                continue
            name, value = match.groups()
            if value and value[0:1] == value[-1:] and value[0:1] in {'"', "'"}:
                value = value[1:-1]
            elif ' #' in value:
                value = value.split(' #', 1)[0].rstrip()
            os.environ.setdefault(name, value)
    
    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        Validate the configuration file has all required fields.
        
        Args:
            config: Configuration dictionary.
        
        Raises:
            ValueError: If configuration is invalid.
        """
        if not isinstance(config, dict):
            raise ValueError("Configuration must be a YAML mapping")
        required_fields = ['user', 'agents']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"Missing required field in config: {field}")
        
        # Validate user configuration
        if not isinstance(config['user'], dict) or not config['user'].get('name'):
            raise ValueError("User configuration must include a name")
        
        # Validate agent configurations
        if not config['agents'] or not isinstance(config['agents'], list):
            raise ValueError("Configuration must include a list of agents")
        
        if not isinstance(config.get('api_keys', {}), dict):
            raise ValueError("api_keys must be a YAML mapping")
        names = set()
        for i, agent in enumerate(config['agents']):
            if not isinstance(agent, dict):
                raise ValueError(f"Agent at index {i} must be a YAML mapping")
            if 'name' not in agent:
                raise ValueError(f"Agent at index {i} missing required field: name")
            if 'specialty' not in agent:
                raise ValueError(f"Agent at index {i} missing required field: specialty")
            if not isinstance(agent['name'], str) or not agent['name'].strip():
                raise ValueError(f"Agent at index {i} needs a nonempty name")
            if agent['name'].lower() in names:
                raise ValueError("Agent names must be unique")
            names.add(agent['name'].lower())
            provider = agent.get('provider', 'anthropic')
            if provider not in SUPPORTED_PROVIDERS:
                raise ValueError(f"{agent['name']}: provider must be one of {', '.join(sorted(SUPPORTED_PROVIDERS))}")
            if not isinstance(agent.get('system_prompt', ''), str):
                raise ValueError(f"{agent['name']}: system_prompt must be text")
            if provider != 'anthropic' and not agent.get('model'):
                raise ValueError(f"{agent['name']}: model is required for non-Anthropic providers")
            for field, default in [('max_tokens', 4000), ('timeout', 180)]:
                value = agent.get(field, default)
                if type(value) is not int or value <= 0:
                    raise ValueError(f"{agent['name']}: {field} must be a positive integer")
            body = agent.get('extra_body', {})
            if not isinstance(body, dict) or RESERVED_BODY_FIELDS.intersection(body):
                raise ValueError(f"{agent['name']}: extra_body must be a mapping without model/messages/stream/token limits")
            if 'base_url' in agent:
                try:
                    url = urlsplit(agent['base_url'])
                    valid = (url.scheme == 'https' and url.hostname and not url.username
                             and not url.password and not url.query and not url.fragment)
                except (ValueError, TypeError, AttributeError):
                    valid = False
                if not valid:
                    raise ValueError(f"{agent['name']}: base_url must be an HTTPS URL without credentials or query parameters")

    @staticmethod
    def _usable_key(value) -> str:
        if not isinstance(value, str):
            return ''
        value = value.strip()
        if not value or value.upper().startswith(('YOUR_', 'REPLACE_', '<')):
            return ''
        return value

    def agent_settings(self, agent: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve independent credentials/model settings; never log this dict."""
        provider = agent.get('provider', 'anthropic')
        key_name = agent.get('api_key_name', provider)
        if not isinstance(key_name, str) or not key_name.isidentifier():
            raise ValueError(f"{agent['name']}: api_key_name must be a simple identifier")
        provider_env = {'anthropic': 'ANTHROPIC_API_KEY', 'nvidia': 'NVIDIA_API_KEY',
                        'dashscope': 'DASHSCOPE_API_KEY', 'groq': 'GROQ_API_KEY',
                        'gemini': 'GEMINI_API_KEY', 'zhipu': 'ZHIPU_API_KEY'}[provider]
        candidates = [os.environ.get(f'{key_name.upper()}_API_KEY'),
                      self.config.get('api_keys', {}).get(key_name),
                      os.environ.get(provider_env)]
        if provider == 'anthropic':
            candidates.append(self.config.get('anthropic_api_key'))
        api_key = next((self._usable_key(v) for v in candidates if self._usable_key(v)), '')
        return {
            'provider': provider,
            'model': agent.get('model', self.model),
            'api_key': api_key,
            'base_url': agent.get('base_url', BASE_URLS.get(provider)),
            'max_tokens': agent.get('max_tokens', 4000),
            'timeout': agent.get('timeout', 180),
            'extra_body': agent.get('extra_body', {}),
            'system_prompt': agent.get('system_prompt', ''),
        }

    def key_location(self, agent: Dict[str, Any]) -> str:
        provider = agent.get('provider', 'anthropic')
        key_name = agent.get('api_key_name', provider)
        if provider == 'anthropic' and 'api_key_name' not in agent:
            return 'anthropic_api_key / ANTHROPIC_API_KEY'
        location = f'api_keys.{key_name} / {key_name.upper()}_API_KEY'
        if provider == 'nvidia':
            location += ' (or shared NVIDIA_API_KEY)'
        elif provider == 'dashscope':
            location += ' (or DASHSCOPE_API_KEY)'
        return location

    def missing_credentials(self) -> List[str]:
        return [f"{a['name']}: fill {self.key_location(a)}"
                for a in self.agents if not self.agent_settings(a)['api_key']]

    def require_credentials(self) -> None:
        missing = self.missing_credentials()
        if missing:
            raise ValueError('Missing API keys:\n  ' + '\n  '.join(missing))
    
    @property
    def user_name(self) -> str:
        """Get the user's name from config."""
        return self.config['user']['name']
    
    @property
    def anthropic_api_key(self) -> str:
        """Get the Anthropic API key from config."""
        return self.agent_settings({'provider': 'anthropic', 'name': 'Claude'})['api_key']
    
    @property
    def model(self) -> str:
        """Legacy default model for agents without per-agent settings."""
        return self.config.get('model', 'claude-sonnet-4-6')
    
    @property
    def agents(self) -> List[Dict[str, Any]]:
        """Get the list of agent configurations."""
        return self.config['agents']
    
    @property
    def documents_dir(self) -> Optional[str]:
        """Get the documents directory if provided."""
        return self.config.get('documents_dir')


