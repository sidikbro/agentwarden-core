"""Plugin registry with @register_* decorators."""
from __future__ import annotations
import logging
logger = logging.getLogger("agentwarden.registry")
from agentwarden.core.models import Runtime

class _Registered:
    parsers=[]; policies=[]; providers=[]; profiles=[]

_reg = _Registered()

def register_parser(cls):  _reg.parsers.append(cls);  return cls
def register_policy(cls):  _reg.policies.append(cls); return cls
def register_provider(cls):_reg.providers.append(cls);return cls
def register_profile(cls): _reg.profiles.append(cls); return cls

class PluginRegistry:
    def __init__(self):
        self._parsers={}; self._policies={}; self._providers={}; self._profiles={}

    @classmethod
    def build(cls):
        import importlib
        r = cls()
        for mod in ["agentwarden.parsers.openai","agentwarden.parsers.hermes",
                    "agentwarden.policies.rules","agentwarden.policies.classifier","agentwarden.providers.ollama",
                    "agentwarden.providers.openai_provider"]:
            try: importlib.import_module(mod)
            except Exception as e: logger.debug("Skip %s: %s", mod, e)
        for c in _reg.parsers:   r._parsers[c.runtime.value] = c
        for c in _reg.policies:  r._policies[c.name] = c
        for c in _reg.providers: r._providers[c.name] = c
        for c in _reg.profiles:  r._profiles[c.name] = c
        if "generic" not in r._parsers:
            from agentwarden.parsers.openai import OpenAIParser
            r._parsers["generic"] = OpenAIParser
        logger.info("Registry: %d parsers, %d policies, %d providers",
                    len(r._parsers), len(r._policies), len(r._providers))
        return r

    def get_parser(self, runtime: Runtime):
        cls = self._parsers.get(runtime.value, self._parsers.get("generic"))
        if not cls: raise ValueError(f"No parser for {runtime}")
        return cls()

    def get_policies(self):
        instances = [c() for c in self._policies.values()]
        return sorted(instances, key=lambda p: p.priority)

    def get_provider(self, name: str):
        cls = self._providers.get(name)
        if not cls: raise ValueError(f"No provider: {name}. Available: {list(self._providers)}")
        return cls()

    def get_profile(self, name: str):
        cls = self._profiles.get(name)
        if not cls: raise ValueError(f"No profile: {name}")
        return cls()

    def summary(self):
        return {"parsers":list(self._parsers),"policies":list(self._policies),
                "providers":list(self._providers),"profiles":list(self._profiles)}

_global: PluginRegistry | None = None
def get_registry():
    global _global
    if _global is None: _global = PluginRegistry.build()
    return _global
