"""Delay native compatibility construction until a consumer actually needs it."""

from threading import Lock


class DeferredPlanner:
    def __init__(self, factory, model):
        self._factory = factory
        self._value = None
        self._lock = Lock()
        self._initializers = []
        self.planner_model = model
        self.router = DeferredRouter(self)

    def get(self):
        with self._lock:
            if self._value is None:
                value = self._factory()
                for initialize in self._initializers:
                    initialize(value)
                self._initializers.clear()
                self._value = value
            return self._value

    def configure(self, initialize):
        """Apply configuration before publishing the planner to its first caller."""
        with self._lock:
            if self._value is None:
                self._initializers.append(initialize)
            else:
                initialize(self._value)

    def peek(self):
        with self._lock:
            return self._value


class DeferredRouter:
    def __init__(self, planner):
        self._planner = planner

    def __getattr__(self, name):
        return getattr(self._planner.get().router, name)
