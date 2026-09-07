const form = document.querySelector("#search-form");
const input = document.querySelector("#query");
const button = document.querySelector("#search-button");
const results = document.querySelector("#results");
const statusBox = document.querySelector("#status");
const validation = document.querySelector("#validation-message");
const clarification = document.querySelector("#clarification");
const clarificationQuestion = document.querySelector("#clarification-question");
const clarificationOptions = document.querySelector("#clarification-options");

function setStatus(message = "") {
  statusBox.textContent = message;
  statusBox.hidden = !message;
}

function showValidation(message = "") {
  validation.textContent = message;
  validation.hidden = !message;
}

function hideClarification() {
  clarification.hidden = true;
  clarificationOptions.replaceChildren();
  clarificationQuestion.textContent = "";
}

function setBusy(busy, label = "Search") {
  button.disabled = busy;
  button.textContent = busy ? "Searching…" : label;
}

function documentUrl(documentId) {
  // The identifier comes from the search index; the browser never supplies a path.
  return `/documents/by-id/${encodeURIComponent(documentId)}`;
}

function renderResults(items) {
  results.replaceChildren();
  for (const item of items) {
    const card = document.createElement("article");
    card.className = "result";
    const heading = document.createElement("h2");
    heading.textContent = item.filename;
    card.append(heading);
    // Two documents can share a filename in different folders; show the
    // corpus-relative folder so they can be told apart.
    if (item.folder) {
      const location = document.createElement("p");
      location.className = "result-folder";
      location.textContent = item.folder.split("/").join(" / ");
      card.append(location);
    }
    const detail = document.createElement("p");
    detail.innerHTML = `<span class="label">Relevant section:</span> `;
    detail.append(document.createTextNode(item.section));
    if (item.page !== null) {
      detail.append(document.createTextNode(` · Page ${item.page}`));
    }
    const open = document.createElement("a");
    open.className = "open-document";
    open.href = documentUrl(item.document_id);
    open.target = "_blank";
    open.rel = "noopener";
    open.textContent = "Open Document";
    card.append(detail, open);
    results.append(card);
  }
}

async function runSearch(query, choice = null) {
  hideClarification();
  results.replaceChildren();
  setBusy(true);
  setStatus("Searching process documents…");
  try {
    const body = { query, limit: 5 };
    if (choice) body.clarification = choice;
    const response = await fetch("/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || "The search service could not complete the request.");
    if (!payload.results.length) {
      setStatus("No matching documents were found. Try a more specific process name or task.");
      return;
    }
    const count = payload.results.length;
    setStatus(`${count} matching document${count === 1 ? "" : "s"} found${choice ? ` for “${choice}”` : ""}.`);
    renderResults(payload.results);
  } catch (error) {
    setStatus("");
    showValidation(error instanceof Error ? error.message : "A network error occurred. Please try again.");
  } finally {
    setBusy(false);
  }
}

function showClarification(query, payload) {
  results.replaceChildren();
  setStatus("");
  clarificationQuestion.textContent = payload.question || "What are you looking for?";
  clarificationOptions.replaceChildren();

  for (const option of payload.options) {
    const choice = document.createElement("button");
    choice.type = "button";
    choice.className = "clarification-option";
    choice.textContent = option.label;
    choice.addEventListener("click", () => runSearch(query, option.value));
    clarificationOptions.append(choice);
  }

  // Always offered, so the clarification step can never block a search.
  const all = document.createElement("button");
  all.type = "button";
  all.className = "clarification-option secondary";
  all.textContent = "Search all documents";
  all.addEventListener("click", () => runSearch(query));
  clarificationOptions.append(all);

  const change = document.createElement("button");
  change.type = "button";
  change.className = "clarification-change";
  change.textContent = "Change query";
  change.addEventListener("click", () => {
    hideClarification();
    setStatus("");
    input.focus();
    input.select();
  });
  clarificationOptions.append(change);

  clarification.hidden = false;
}

async function analyze(query) {
  // A failure here must never stop a search, so the caller treats any problem
  // as "no clarification needed".
  const response = await fetch("/query-understanding", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!response.ok) throw new Error("query understanding unavailable");
  return response.json();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = input.value.trim();
  showValidation();
  hideClarification();
  results.replaceChildren();
  if (!query) {
    showValidation("Enter a process or task to search.");
    input.focus();
    return;
  }

  setBusy(true);
  setStatus("Checking your search…");
  let prepared = null;
  try {
    prepared = await analyze(query);
  } catch {
    prepared = null;
  } finally {
    setBusy(false);
  }

  if (prepared && prepared.needs_clarification && (prepared.options || []).length) {
    showClarification(query, prepared);
    return;
  }
  await runSearch(query);
});
