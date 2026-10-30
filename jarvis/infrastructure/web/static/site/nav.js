(function () {
  "use strict";

  var LINKS = [
    { href: "/", label: "Inicio" },
    { href: "/deposito", label: "Depósito de agua" },
    { href: "/memoria", label: "Memoria" },
  ];

  function isActive(href) {
    var path = window.location.pathname;
    if (href === "/") {
      return path === "/" || path === "/index.html";
    }
    return path === href;
  }

  function buildHeader() {
    var header = document.createElement("header");
    header.className = "site-header";

    var titleLink = document.createElement("a");
    titleLink.href = "/";
    titleLink.className = "site-title";
    titleLink.textContent = "Jarvis";

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "site-menu-toggle";
    toggle.setAttribute("aria-controls", "site-nav");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Abrir menú");
    toggle.textContent = "☰";

    var nav = document.createElement("nav");
    nav.id = "site-nav";
    nav.className = "site-nav";
    nav.hidden = true;

    var list = document.createElement("ul");
    LINKS.forEach(function (link) {
      var item = document.createElement("li");
      var anchor = document.createElement("a");
      anchor.href = link.href;
      anchor.textContent = link.label;
      if (isActive(link.href)) {
        anchor.classList.add("active");
        anchor.setAttribute("aria-current", "page");
      }
      item.appendChild(anchor);
      list.appendChild(item);
    });
    nav.appendChild(list);

    header.appendChild(titleLink);
    header.appendChild(toggle);
    header.appendChild(nav);

    function closeMenu(focusToggle) {
      if (nav.hidden) return;
      nav.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      if (focusToggle !== false) {
        toggle.focus();
      }
    }

    function openMenu() {
      nav.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
    }

    toggle.addEventListener("click", function () {
      if (nav.hidden) {
        openMenu();
      } else {
        closeMenu();
      }
    });

    nav.addEventListener("click", function (event) {
      if (event.target.tagName === "A") {
        closeMenu(false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !nav.hidden) {
        closeMenu();
      }
    });

    document.addEventListener("click", function (event) {
      if (nav.hidden || header.contains(event.target)) {
        return;
      }
      closeMenu(false);
    });

    document.body.insertBefore(header, document.body.firstChild);
    document.body.classList.add("has-site-header");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildHeader);
  } else {
    buildHeader();
  }
})();
