// Show/hide password toggle (progressive enhancement; forms work without JS).
document.querySelectorAll(".js-toggle-password").forEach((button) => {
  button.addEventListener("click", () => {
    const input = document.getElementById(button.dataset.target);
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    button.textContent = reveal ? "Hide" : "Show";
    button.setAttribute("aria-label", reveal ? "Hide password" : "Show password");
  });
});
