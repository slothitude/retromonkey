/* RetroMonkey AliExpress Scraper — popup controller */

const scrapeBtn = document.getElementById('scrapeBtn');
const copyBtn = document.getElementById('copyBtn');
const sendBtn = document.getElementById('sendBtn');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');

let lastData = null;

scrapeBtn.addEventListener('click', async () => {
  scrapeBtn.disabled = true;
  statusEl.textContent = 'Scraping...';

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // Call window.__rm.scrape() in the MAIN world and read window.__rm.data
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: 'MAIN',
      func: () => {
        if (!window.__rm || typeof window.__rm.scrape !== 'function') {
          return { error: '__rm not injected — reload the page' };
        }
        return window.__rm.scrape();
      },
    });

    if (!results || !results[0] || !results[0].result) {
      statusEl.textContent = 'No result returned.';
      scrapeBtn.disabled = false;
      return;
    }

    const data = results[0].result;

    if (data.error) {
      statusEl.textContent = 'Error: ' + data.error;
      scrapeBtn.disabled = false;
      return;
    }

    lastData = data;
    statusEl.textContent = `Found ${data.product_count} products on ${data.url.split('/')[2]}`;
    resultsEl.style.display = 'block';
    resultsEl.textContent = JSON.stringify(data, null, 2);
    copyBtn.style.display = 'block';
    sendBtn.style.display = 'block';
  } catch (err) {
    statusEl.textContent = 'Error: ' + err.message;
  }

  scrapeBtn.disabled = false;
});

copyBtn.addEventListener('click', () => {
  if (!lastData) return;
  navigator.clipboard.writeText(JSON.stringify(lastData, null, 2))
    .then(() => { statusEl.textContent = 'Copied to clipboard!'; })
    .catch(err => { statusEl.textContent = 'Copy failed: ' + err.message; });
});

sendBtn.addEventListener('click', async () => {
  if (!lastData) return;
  sendBtn.disabled = true;
  statusEl.textContent = 'Sending to RetroMonkey API...';

  try {
    const resp = await fetch('http://localhost:5000/api/sourcing/aliexpress-scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(lastData),
    });

    if (resp.ok) {
      const result = await resp.json();
      statusEl.textContent = 'Saved ' + (result.saved || 0) + ' products to RetroMonkey.';
    } else {
      const text = await resp.text();
      statusEl.textContent = 'API error ' + resp.status + ': ' + text.substring(0, 80);
    }
  } catch (err) {
    statusEl.textContent = 'API unreachable (' + err.message + '). Copy JSON instead.';
  }

  sendBtn.disabled = false;
});
