export function clone(value) {
  if (typeof structuredClone === "function") return structuredClone(value);
  return JSON.parse(JSON.stringify(value));
}

export function createElement(tag, options = {}) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = String(options.text);
  for (const [key, value] of Object.entries(options.attrs || {})) {
    if (value !== undefined && value !== null && value !== false) element.setAttribute(key, String(value));
  }
  return element;
}

export function clearElement(element) {
  while (element?.firstChild) element.removeChild(element.firstChild);
}

export function unique(values) {
  return [...new Set((values || []).filter((item) => item !== undefined && item !== null && item !== ""))];
}

const BLOCKED_PATH_PARTS = new Set(["__proto__", "prototype", "constructor"]);

export function pathParts(path) {
  const normalized = String(path || "").replace(/\[(\d+)\]/g, ".$1");
  if (normalized.includes("[") || normalized.includes("]")) throw new Error("Unsafe object path rejected");
  const parts = normalized.split(".").filter(Boolean);
  if (parts.some((part) => BLOCKED_PATH_PARTS.has(part))) {
    throw new Error("Unsafe object path rejected");
  }
  return parts;
}

export function getValueAtPath(object, path) {
  return pathParts(path).reduce((current, part) => (current == null ? undefined : current[part]), object);
}

export function setValueAtPath(object, path, value) {
  const parts = pathParts(path);
  if (!parts.length) return object;
  let current = object;
  for (let index = 0; index < parts.length - 1; index += 1) {
    const part = parts[index];
    const nextIsIndex = /^\d+$/.test(parts[index + 1]);
    if (Array.isArray(current)) {
      if (!/^\d+$/.test(part)) throw new Error("Array path requires a numeric index");
      const itemIndex = Number(part);
      if (typeof current[itemIndex] !== "object" || current[itemIndex] === null) current[itemIndex] = nextIsIndex ? [] : {};
      current = current[itemIndex];
    } else {
      if (typeof current[part] !== "object" || current[part] === null) current[part] = nextIsIndex ? [] : {};
      current = current[part];
    }
  }
  const finalPart = parts[parts.length - 1];
  if (Array.isArray(current) && !/^\d+$/.test(finalPart)) throw new Error("Array path requires a numeric index");
  current[finalPart] = value;
  return object;
}

export function safeText(value) {
  return value === undefined || value === null ? "" : String(value);
}

// Answer/description text from the LLM sometimes carries light markdown
// (e.g. **bold**). Render it without innerHTML so we never open an
// HTML-injection surface; unsupported syntax is left as literal text.
export function createMarkdownParagraph(text, options = {}) {
  const p = createElement("p", options);
  const source = safeText(text);
  const pattern = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(source))) {
    if (match.index > lastIndex) p.append(document.createTextNode(source.slice(lastIndex, match.index)));
    p.append(createElement("strong", { text: match[1] }));
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < source.length) p.append(document.createTextNode(source.slice(lastIndex)));
  return p;
}
