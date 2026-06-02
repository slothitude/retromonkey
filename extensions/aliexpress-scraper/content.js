/* RetroMonkey AliExpress Scraper — content script
 *
 * Injects window.__rm into the MAIN page world so CDP can call:
 *   window.__rm.scrape()   → returns products array
 *   window.__rm.data       → last scraped data
 */

(function inject() {
  // Avoid double-inject
  if (window.__rm) return;

  const script = document.createElement('script');
  script.textContent = `
(function() {
  if (window.__rm) return;
  window.__rm = { data: null, error: null };

  function get(sel, ctx) {
    for (const s of sel) {
      const el = ctx.querySelector(s);
      if (el) { const t = el.textContent.trim(); if (t) return t; }
    }
    return '';
  }

  function getAttr(sel, attr, ctx) {
    for (const s of sel) {
      const el = ctx.querySelector(s);
      if (el) { const v = el.getAttribute(attr); if (v) return v; }
    }
    return '';
  }

  function extractProduct(card, index) {
    const href = getAttr(['a[href*="/item/"]'], 'href', card) || '';
    const fullUrl = href.startsWith('http') ? href : (href ? 'https://www.aliexpress.com' + href : '');
    const imgSrc = getAttr(['img[src*="alicdn"]', 'img'], 'src', card)
                || getAttr(['img'], 'data-src', card);

    return {
      index: index + 1,
      title: get(['[itemprop="name"]','[data-spm="title"]','.item-title','h3','a[title]','[class*="title"]'], card),
      price: get(['.price-current','.price-value','[class*="price"]','[class*="Price"]'], card),
      original_price: get(['.price-original','[class*="original"]'], card),
      url: fullUrl,
      image: imgSrc,
      orders: get(['[class*="sold"]','[class*="order"]','[class*="history"]'], card),
      rating: get(['[class*="rating"]','[class*="star"]'], card),
      shipping: get(['[class*="ship"]','[class*="delivery"]','[class*="free-shipping"]'], card),
      store: get(['[class*="store"]','[class*="shop"]','[class*="seller"]','span[class*="name"]'], card),
    };
  }

  window.__rm.scrape = function() {
    try {
      const url = window.location.href;
      const products = [];

      const cardSelectors = [
        '[data-spm="item"]',
        'div.search-item-card',
        '.manhattan-container',
        'div[J-orig], div[temprop]',
        '.items-item',
        '[class*="product-card"]',
        '[class*="SearchCard"]',
      ];

      let cards = [];
      for (const sel of cardSelectors) {
        cards = document.querySelectorAll(sel);
        if (cards.length > 0) break;
      }

      // Fallback: anchors linking to /item/
      if (cards.length === 0) {
        const seen = new Set();
        document.querySelectorAll('a[href*="/item/"]').forEach(a => {
          const href = a.getAttribute('href') || '';
          if (!seen.has(href) && href.includes('/item/')) {
            seen.add(href);
            cards.push(a.closest('div[class]') || a.parentElement || a);
          }
        });
      }

      cards.forEach((card, i) => {
        const p = extractProduct(card, i);
        if (p.title) products.push(p);
      });

      window.__rm.data = {
        url,
        product_count: products.length,
        products,
        scraped_at: new Date().toISOString(),
      };
      window.__rm.error = null;
      return window.__rm.data;
    } catch (err) {
      window.__rm.error = err.message;
      return { error: err.message, products: [] };
    }
  };
})();
`;
  (document.head || document.documentElement).appendChild(script);
  script.remove();
})();
