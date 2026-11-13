// The landing page's only script: no requests, nothing from another site.
"use strict";

// Swagger UI used to be at the root, so links like …/#/Chats/listChatMessages were shared. They go
// on to api/ with the same part after '#'. This runs in <head>, before the page is drawn.
function toSwaggerUi() {
  if (window.location.hash.indexOf("#/") === 0) {
    window.location.replace("api/" + window.location.hash);
  }
}
toSwaggerUi();
window.addEventListener("hashchange", toSwaggerUi); // such a link followed from this page itself

// Which download fits this computer: a guess from the browser, never sent anywhere.
function yourSystem() {
  const agent = navigator.userAgent || "";
  const platform = (navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || "";
  if (/Android|iPhone|iPad|iPod/i.test(agent)) return null; // a phone or tablet: no desktop app
  if (/Win/i.test(platform) || /Windows/i.test(agent)) return "windows";
  if (/Mac/i.test(platform) || /Macintosh/i.test(agent)) return "macos";
  if (/Linux/i.test(platform) || /Linux/i.test(agent)) {
    return /aarch64|arm64|armv8/i.test(platform + " " + agent) ? "linux-aarch64" : "linux-x86_64";
  }
  return null;
}

document.addEventListener("DOMContentLoaded", function () {
  const system = yourSystem();
  const list = document.getElementById("downloads");
  const yours = system && list && list.querySelector('[data-system="' + system + '"]');
  if (yours) {
    yours.classList.add("yours");
    yours.insertAdjacentHTML("afterbegin", '<span class="download-tag">For this computer</span>');
    list.insertBefore(yours, list.firstChild);
  }

  document.querySelectorAll("button.copy").forEach(function (button) {
    button.addEventListener("click", function () {
      const text = document.getElementById(button.dataset.copy).textContent;
      if (!navigator.clipboard) return;
      navigator.clipboard.writeText(text).then(function () {
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = "Copy"; }, 1500);
      });
    });
  });
});
