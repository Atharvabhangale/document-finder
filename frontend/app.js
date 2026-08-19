const form = document.querySelector("#search-form");
const input = document.querySelector("#query");
const button = document.querySelector("#search-button");
const results = document.querySelector("#results");
const statusBox = document.querySelector("#status");
const validation = document.querySelector("#validation-message");

function setStatus(message = "") {
  statusBox.textContent = message;
  statusBox.hidden = !message;
}

function showValidation(message = "") {
  validation.textContent = message;
  validation.hidden = !message;
}

function documentUrl(filename) {
  return `/documents/${encodeURIComponent(filename)}`;
}

function renderResults(items) {
  results.replaceChildren();
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "result";
    const heading = document.createElement("h2");
    heading.textContent = item.filename;
    const detail = document.createElement("p");
    detail.innerHTML = `<span class="label">Relevant section:</span> `;
    detail.append(document.createTextNode(item.section));
    if (item.page !== null) {
      detail.append(document.createTextNode(` · Page ${item.page}`));
    }
    const open = document.createElement("a");
    open.className = "open-document";
    open.href = documentUrl(item.filename);
    open.target = "_blank";
    open.rel = "noopener";
    open.textContent = "Open Document";
    card.append(heading, detail, open);
    results.append(card);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = input.value.trim();
  showValidation();
  results.replaceChildren();
  if (!query) {
    showValidation("Enter a process or task to search.");
    input.focus();
    return;
  }
  button.disabled = true;
  button.textContent = "Searching…";
  setStatus("Searching process documents…");
  try {
    const response = await fetch("/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, limit: 5 }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "The search service could not complete the request.");
    if (!payload.results.length) {
      setStatus("No matching documents were found. Try a more specific process name or task.");
      return;
    }
    setStatus(`${payload.results.length} matching document${payload.results.length === 1 ? "" : "s"} found.`);
    renderResults(payload.results);
  } catch (error) {
    setStatus("");
    showValidation(error instanceof Error ? error.message : "A network error occurred. Please try again.");
  } finally {
    button.disabled = false;
    button.textContent = "Search";
  }
});
