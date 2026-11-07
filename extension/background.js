// Calls our server for the content script. The API key stays on the server and never reaches the browser.
const SERVER_URL = "https://noir-microburbs.vercel.app";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type !== "lookup") return false;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 30000);
  fetch(`${SERVER_URL}/lookup?${new URLSearchParams(message.params)}`, { signal: controller.signal })
    .then((response) => (response.ok ? response.json() : Promise.reject(new Error(response.status))))
    .then((data) => sendResponse({ ok: true, data }))
    .catch(() => sendResponse({ ok: false }))
    .finally(() => clearTimeout(timer));

  return true; // the answer comes later
});
