const puppeteer = require('puppeteer');

async function simulateVisit(url, proxy) {
    const browser = await puppeteer.launch({ args: ['--no-sandbox', '--disable-setuid-sandbox'] });
    const page = await browser.newPage();
    if (proxy) {
        await page._client.send('Network.setProxy', { proxyServer: proxy });
    }
    await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3');
    await page.goto(url, { waitUntil: 'networkidle2' });
    await page.waitForTimeout(2000);  // Espera 2 segundos para simular la interacción del usuario
    await browser.close();
}

const url = process.argv[2];
const proxy = process.argv[3];
simulateVisit(url, proxy);
