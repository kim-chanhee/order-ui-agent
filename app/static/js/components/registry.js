const componentRegistry = new Map();

export function registerComponent(type, renderer) {
  componentRegistry.set(type, renderer);
}

export function renderComponent(block, context) {
  const renderer = componentRegistry.get(block.type) || componentRegistry.get("unknown");
  return renderer(block, context);
}

export function initializeDefaultComponents(renderers) {
  for (const [type, renderer] of Object.entries(renderers)) registerComponent(type, renderer);
}

export function registeredComponentTypes() {
  return [...componentRegistry.keys()];
}

export function supportedComponentTypes() {
  return registeredComponentTypes().filter((type) => type !== "unknown");
}
