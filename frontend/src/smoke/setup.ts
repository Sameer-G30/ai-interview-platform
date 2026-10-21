// Vitest setup for the frontend smoke suite. Runs before each test file, in jsdom, with no browser.
import { cleanup } from "@testing-library/react" // unmounts the previous render so routers do not stack
import "@testing-library/jest-dom/vitest" // registers toBeInTheDocument on vitest's expect
import { afterEach } from "vitest" // hook that runs after every smoke test

// jsdom does not implement matchMedia. The sidebar and the theme toggle both call it on mount.
if (typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true, // tests can replace the stub if a later case needs a real query
    value: (query: string): MediaQueryList =>
      ({
        matches: false, // desktop-width default; smoke tests do not resize the viewport
        media: query, // echo the query the caller asked about
        onchange: null, // legacy MediaQueryList field; nothing listens in these tests
        addListener: () => undefined, // deprecated API the sidebar does not use, but some libs probe it
        removeListener: () => undefined, // pair for addListener
        addEventListener: () => undefined, // useIsMobile subscribes with this
        removeEventListener: () => undefined, // useIsMobile cleans up with this
        dispatchEvent: () => false, // MediaQueryList extends EventTarget
      }) as MediaQueryList, // the stub only implements the methods this app calls
  })
}

// Radix checks pointer capture on click. jsdom leaves those methods missing.
if (typeof Element.prototype.hasPointerCapture !== "function") {
  Element.prototype.hasPointerCapture = () => false // no pointer is captured in jsdom
  Element.prototype.setPointerCapture = () => undefined // ignore capture requests from menus
  Element.prototype.releasePointerCapture = () => undefined // ignore the matching release
}

// jsdom's scrollIntoView throws "not implemented", which fails a click that scrolls a field into view.
Element.prototype.scrollIntoView = () => undefined // smoke tests never assert scroll position

// Some layout code constructs ResizeObserver. Install a no-op when the DOM does not provide one.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserverStub {
    observe(): void {} // sidebar width tracking is irrelevant to the journey assertions
    unobserve(): void {} // pair for observe
    disconnect(): void {} // pair for observe
  }
}

afterEach(() => {
  cleanup() // drop the rendered tree so the next test gets a fresh router
})
