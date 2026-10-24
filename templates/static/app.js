
const form = document.getElementById("uploadForm");

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const status = document.getElementById("status");
    const result = document.getElementById("result");
    const button = form.querySelector('button[type="submit"]');

    status.textContent = "ဗီဒီယိုကို လုပ်ဆောင်နေပါတယ်...";
    if (button) button.disabled = true;
    if (result) result.innerHTML = "";

    try {
      const response = await fetch("/api/process", {
        method: "POST",
        body: new FormData(form)
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "လုပ်ဆောင်မှု မအောင်မြင်ပါ");
      }

      status.textContent = "ပြီးပါပြီ။";
      if (result && data.output_url) {
        const link = document.createElement("a");
        link.href = data.output_url;
        link.textContent = "ပြီးသွားတဲ့ ဗီဒီယိုကို ကြည့်ရန်";
        link.target = "_blank";
        result.appendChild(link);
      }
    } catch (error) {
      status.textContent =
        error.message || "အမှားတစ်ခု ဖြစ်သွားပါတယ်။";
    } finally {
      if (button) button.disabled = false;
    }
  });
}
