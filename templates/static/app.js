
const form = document.getElementById("form");

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const status = document.getElementById("status");
    const download = document.getElementById("download");
    const button = document.getElementById("go");

    if (status) {
      status.textContent = "ဗီဒီယိုကို လုပ်ဆောင်နေပါတယ်။ ခဏစောင့်ပါ...";
    }

    if (button) {
      button.disabled = true;
      button.textContent = "လုပ်ဆောင်နေပါတယ်...";
    }

    if (download) {
      download.classList.add("hidden");
      download.removeAttribute("href");
    }

    try {
      const response = await fetch("/api/process", {
        method: "POST",
        body: new FormData(form)
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.error || "လုပ်ဆောင်မှု မအောင်မြင်ပါ"
        );
      }

      if (data.output_url && download) {
        download.href = data.output_url;
        download.classList.remove("hidden");
        download.textContent =
          "⬇️ ပြီးသွားတဲ့ ဗီဒီယိုကို Download လုပ်မယ်";
      }

      if (status) {
        status.textContent = data.output_url
          ? "ပြီးပါပြီ။ အောက်ကခလုတ်ကိုနှိပ်ပြီး ဗီဒီယိုယူနိုင်ပါပြီ။"
          : "ပြီးပါပြီ။ ဒါပေမဲ့ ဗီဒီယိုလင့်ခ် မရရှိသေးပါ။";
      }
    } catch (error) {
      if (status) {
        status.textContent =
          "အမှား: " + (error.message || "ပြန်စမ်းကြည့်ပါ။");
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "✨ One Click Recap လုပ်မယ်";
      }
    }
  });
}
