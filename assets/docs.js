(() => {
  const ui = JSON.parse(document.body.dataset.ui);
  const treeKey = `hugo-docs:${document.body.dataset.siteKey}:tree`;
  const sidebar = document.getElementById("sidebar");
  const menuButton = document.getElementById("menu-toggle");
  const backdrop = document.querySelector(".nav-backdrop");
  const main = document.getElementById("main");
  const mobile = matchMedia("(max-width: 760px)");
  let navigationOpen = false;

  const setNavigation = (open, restoreFocus = true) => {
    navigationOpen = open && mobile.matches;
    document.body.classList.toggle("nav-open", navigationOpen);
    menuButton.setAttribute("aria-expanded", String(navigationOpen));
    menuButton.setAttribute("aria-label", navigationOpen ? ui.closeNavigation : ui.openNavigation);
    menuButton.querySelector("path").setAttribute("d", navigationOpen ? "m6 6 12 12M6 18 18 6" : "M4 6h16M4 12h16M4 18h16");
    backdrop.hidden = !navigationOpen;
    main.inert = navigationOpen;
    sidebar.inert = mobile.matches && !navigationOpen;
    if (navigationOpen) sidebar.querySelector("[aria-current='page'], a, button")?.focus();
    else if (restoreFocus && mobile.matches) menuButton.focus();
  };
  menuButton.addEventListener("click", () => setNavigation(!navigationOpen));
  backdrop.addEventListener("click", () => setNavigation(false));
  mobile.addEventListener("change", () => setNavigation(false, false));
  setNavigation(false, false);

  let savedTree = {};
  try { savedTree = JSON.parse(localStorage.getItem(treeKey) || "{}"); } catch {}
  if (!savedTree || typeof savedTree !== "object") savedTree = {};
  for (const button of document.querySelectorAll(".tree-toggle")) {
    const target = document.getElementById(button.getAttribute("aria-controls"));
    const branch = button.closest(".nav-item").hasAttribute("data-current-branch");
    const update = (open) => {
      button.setAttribute("aria-expanded", String(open));
      button.setAttribute("aria-label", `${open ? ui.collapseFolder : ui.expandFolder} ${button.dataset.title}`);
      target.hidden = !open;
    };
    if (!branch && typeof savedTree[button.dataset.section] === "boolean") update(savedTree[button.dataset.section]);
    button.addEventListener("click", () => {
      const open = button.getAttribute("aria-expanded") !== "true";
      update(open);
      savedTree[button.dataset.section] = open;
      try { localStorage.setItem(treeKey, JSON.stringify(savedTree)); } catch {}
    });
  }

  for (const panel of document.querySelectorAll(".page-tree, .page-outline")) {
    let pending = false;
    const updateEdges = () => {
      pending = false;
      const top = Math.max(0, panel.scrollTop);
      const bottom = Math.max(0, panel.scrollHeight - panel.clientHeight - top);
      for (const [edge, remaining] of [["top", top], ["bottom", bottom]]) {
        const value = `${remaining <= 1 ? 0 : Math.min(64, remaining)}px`;
        const property = `--sidebar-fade-${edge}`;
        if (panel.style.getPropertyValue(property) !== value) panel.style.setProperty(property, value);
      }
    };
    const scheduleEdges = () => {
      if (!pending) { pending = true; requestAnimationFrame(updateEdges); }
    };
    const resizeObserver = new ResizeObserver(scheduleEdges);
    const observeContent = () => {
      resizeObserver.disconnect();
      resizeObserver.observe(panel);
      for (const child of panel.children) resizeObserver.observe(child);
      scheduleEdges();
    };
    new MutationObserver(observeContent).observe(panel, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["hidden", "class", "open"],
    });
    panel.addEventListener("scroll", scheduleEdges, { passive: true });
    addEventListener("resize", scheduleEdges, { passive: true });
    addEventListener("pageshow", scheduleEdges);
    document.fonts.ready.then(scheduleEdges);
    observeContent();
    updateEdges();
  }

  const outlineLinks = [...document.querySelectorAll(".page-outline nav a")];
  const headings = [...document.querySelectorAll(".hc-content :is(h2,h3)[id]")];
  let scheduled = false;
  const updateOutline = () => {
    const current = headings.filter((heading) => heading.getBoundingClientRect().top <= 120).at(-1);
    for (const link of outlineLinks) {
      if (current && decodeURIComponent(link.hash.slice(1)) === current.id) link.setAttribute("aria-current", "location");
      else link.removeAttribute("aria-current");
    }
    scheduled = false;
  };
  addEventListener("scroll", () => {
    if (!scheduled) { scheduled = true; requestAnimationFrame(updateOutline); }
  }, { passive: true });
  updateOutline();

  const dialog = document.getElementById("search-dialog");
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");
  const status = document.getElementById("search-status");
  const retry = document.getElementById("search-retry");
  let previousFocus;
  let indexPromise;
  let queryVersion = 0;
  let selected = -1;
  const normalize = (text) => text.toLocaleLowerCase(document.documentElement.lang || "en").replaceAll("ё", "е");
  const getIndex = () => {
    if (!indexPromise) {
      indexPromise = fetch(document.body.dataset.searchIndex)
        .then((response) => {
          if (!response.ok) throw new Error("Search index unavailable");
          return response.json();
        })
        .then((pages) => pages.map((page) => ({ ...page, titleSearch: normalize(page.title), textSearch: normalize(`${page.title} ${page.description} ${page.content}`) })))
        .catch((error) => { indexPromise = undefined; throw error; });
    }
    return indexPromise;
  };
  const highlight = (element, text, terms) => {
    let offset = 0;
    const normalized = normalize(text);
    while (offset < text.length) {
      let found = -1;
      let length = 0;
      for (const term of terms) {
        const position = normalized.indexOf(term, offset);
        if (position !== -1 && (found === -1 || position < found)) { found = position; length = term.length; }
      }
      if (found === -1) { element.append(document.createTextNode(text.slice(offset))); break; }
      element.append(document.createTextNode(text.slice(offset, found)));
      const mark = document.createElement("mark");
      mark.textContent = text.slice(found, found + length);
      element.append(mark);
      offset = found + length;
    }
  };
  const setSelected = (position, scroll = false) => {
    const options = [...results.children];
    selected = options.length ? (position + options.length) % options.length : -1;
    options.forEach((option, i) => option.setAttribute("aria-selected", String(i === selected)));
    if (selected >= 0) {
      input.setAttribute("aria-activedescendant", options[selected].id);
      if (scroll) options[selected].scrollIntoView({ block: "nearest" });
    } else input.removeAttribute("aria-activedescendant");
  };
  const search = async () => {
    const version = ++queryVersion;
    const query = normalize(input.value.trim());
    const terms = query.split(/\s+/).filter(Boolean);
    results.replaceChildren();
    setSelected(-1);
    input.setAttribute("aria-expanded", "false");
    status.textContent = ui.searchLoading;
    retry.hidden = true;
    try {
      const pages = await getIndex();
      if (version !== queryVersion) return;
      const matches = pages.filter((page) => terms.every((term) => page.textSearch.includes(term)));
      if (query) matches.sort((a, b) => {
        const score = (page) => (page.titleSearch === query ? 100 : 0) + (page.titleSearch.startsWith(query) ? 30 : 0) + terms.filter((term) => page.titleSearch.includes(term)).length * 10;
        return score(b) - score(a);
      });
      const shown = matches.slice(0, query ? 15 : 5);
      status.textContent = query ? (matches.length ? ui.searchCount.replace("{count}", matches.length) + (matches.length > 15 ? ui.searchLimit : "") : ui.searchEmpty) : ui.searchSuggestions;
      for (const [position, page] of shown.entries()) {
        const item = document.createElement("li");
        item.id = `search-option-${position}`;
        item.setAttribute("role", "option");
        const link = document.createElement("a");
        link.href = page.url;
        link.className = "search-result";
        const section = document.createElement("span");
        section.className = "search-result-path";
        section.textContent = page.section;
        const title = document.createElement("span");
        title.className = "search-result-title";
        highlight(title, page.title, terms);
        const excerpt = document.createElement("span");
        excerpt.className = "search-result-excerpt";
        const content = page.content.replace(/\s+/g, " ");
        const first = terms.length ? Math.max(0, normalize(content).indexOf(terms[0])) : 0;
        const start = Math.max(0, first - 45);
        const snippet = query ? `${start ? "…" : ""}${content.slice(start, start + 160)}${content.length > start + 160 ? "…" : ""}` : (page.description || content.slice(0, 160));
        highlight(excerpt, snippet, terms);
        link.append(section, title, excerpt);
        item.append(link);
        item.addEventListener("pointermove", () => setSelected(position));
        results.append(item);
      }
      input.setAttribute("aria-expanded", String(shown.length > 0));
      setSelected(0);
    } catch {
      if (version !== queryVersion) return;
      status.textContent = ui.searchError;
      retry.hidden = false;
    }
  };
  const openSearch = () => {
    previousFocus = document.activeElement;
    setNavigation(false, false);
    dialog.showModal();
    input.focus();
    input.select();
    search();
  };
  document.querySelectorAll("[data-open-search]").forEach((button) => button.addEventListener("click", openSearch));
  document.querySelector("[data-close-search]").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  dialog.addEventListener("close", () => {
    queryVersion++;
    if (previousFocus?.getClientRects().length && !previousFocus.closest("[inert]") && getComputedStyle(previousFocus).visibility === "visible") previousFocus.focus();
    else (mobile.matches ? menuButton : document.querySelector(".search-trigger")).focus();
  });
  input.addEventListener("input", search);
  retry.addEventListener("click", search);
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setSelected(selected + (event.key === "ArrowDown" ? 1 : -1), true);
    } else if (event.key === "Enter" && selected >= 0) {
      event.preventDefault();
      results.children[selected].querySelector("a").click();
    }
  });
  document.addEventListener("keydown", (event) => {
    const typing = event.target.matches("input, textarea, select") || event.target.isContentEditable;
    if (((event.ctrlKey || event.metaKey) && ["k", "л"].includes(event.key.toLowerCase())) || (event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey)) {
      event.preventDefault();
      if (dialog.open) dialog.close(); else openSearch();
    }
    if (dialog.open) {
      if (event.key === "Escape") { event.preventDefault(); dialog.close(); }
      return;
    }
    if (!navigationOpen) return;
    if (event.key === "Escape") setNavigation(false);
    if (event.key === "Tab") {
      const focusable = [menuButton, ...sidebar.querySelectorAll("a, button")].filter((element) => element.getClientRects().length);
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
})();
