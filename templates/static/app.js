
const form = document.getElementById("form");

if (!form) {
  alert("Form ကို ရှာမတွေ့ပါ။ HTML ထဲက form ID ကို စစ်ပါ။");
} else {
  form.addEventListener("submit", async function (event) {
    event.preventDefault();

    const status = document.getElementById("status");
    const download = document.getElementById("download");
    const button = document.getElementById("go");

    if (status) status.textContent = "ဗီဒီယိုလုပ်ဆောင်နေပါတယ်။ ခဏစောင့်ပါ...";
    if (button) {
      button.disabled = true;
      button.textContent = "လုပ်ဆောင်နေပါတယ်...";
    }
    if (download) download.classList.add("hidden");

    try {
      const response = await fetch("/api/process", {
        method: "POST",
        body: new FormData(form)
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.error || "လုပ်ဆောင်မှု မအောင်မြင်ပါ");
      }

      if (data.output_url && download) {
        download.href = data.output_url;
        download.classList.remove("hidden");
      }

      if (status) status.textContent = "ပြီးပါပြီ။";
    } catch (error) {
      if (status) status.textContent = "အမှား: " + error.message;
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "✨ One Click Recap လုပ်မယ်";
      }
    }
  });
}
