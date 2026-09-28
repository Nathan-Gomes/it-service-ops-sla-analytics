// Apply the saved theme before first paint (kept out of index.html for the CSP).
try {
  const saved = localStorage.getItem('serviceops.theme');
  if (saved) document.documentElement.dataset.theme = saved;
} catch (error) { /* storage unavailable: keep the default */ }
