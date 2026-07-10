/**
 * PROOF 에이전트 — browserless 원격 브라우저 헬퍼 (Node.js)
 *
 * [Flow: Step 1 (browserless 서버 연결) -> Step 2 (새 페이지 생성) -> Step 3 (작업 수행) -> Step 4 (결과 저장)]
 *
 * 이 모듈은 a1 에 구동 중인 browserless 서버(http://192.168.1.50:20047)에 원격으로 연결하여
 * 웹 브라우징 작업을 수행한다. VM 내부에 Chrome 을 설치하지 않아 메모리를 절약한다.
 *
 * 사용법:
 *   const { BrowserlessSession } = require('./browserless-helper');
 *   const session = new BrowserlessSession();
 *   await session.connect();
 *   const screenshot = await session.screenshot('https://example.com');
 *   await session.saveToWorkspace(screenshot, '/workspace/screenshot.png');
 *   await session.close();
 */

const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

// browserless 서버 URL (a1, 기존 구동 중)
const BROWSERLESS_URL = process.env.BROWSERLESS_URL || 'http://192.168.1.50:20047';

/**
 * browserless 서버에 연결하여 웹 브라우징 작업을 수행하는 세션 클래스.
 */
class BrowserlessSession {
  /**
   * @param {string} [token] - browserless API 토큰 (인증이 활성화된 경우)
   */
  constructor(token) {
    this.token = token;
    this.browser = null;
  }

  /**
   * browserless 서버에 CDP WebSocket 으로 연결한다.
   */
  async connect() {
    const wsEndpoint = this.token
      ? `${BROWSERLESS_URL}?token=${this.token}`
      : BROWSERLESS_URL;

    this.browser = await puppeteer.connect({
      browserWSEndpoint: wsEndpoint,
      // browserless 는 자체적으로 Chrome 을 관리하므로 로컬 실행 파일 불필요
    });
    return this.browser;
  }

  /**
   * URL 의 스크린샷을 캡처하여 PNG 버퍼를 반환한다.
   * @param {string} url - 캡처할 웹페이지 URL
   * @param {boolean} [fullPage=true] - 전체 페이지 캡처 여부
   * @returns {Promise<Buffer>} PNG 이미지 버퍼
   */
  async screenshot(url, fullPage = true) {
    if (!this.browser) await this.connect();

    const page = await this.browser.newPage();
    try {
      await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
      const screenshot = await page.screenshot({ fullPage });
      return screenshot;
    } finally {
      await page.close();
    }
  }

  /**
   * URL 의 페이지를 PDF 로 변환하여 버퍼를 반환한다.
   * @param {string} url - PDF 로 변환할 웹페이지 URL
   * @returns {Promise<Buffer>} PDF 버퍼
   */
  async printToPdf(url) {
    if (!this.browser) await this.connect();

    const page = await this.browser.newPage();
    try {
      await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
      const pdf = await page.pdf({ format: 'A4', printBackground: true });
      return pdf;
    } finally {
      await page.close();
    }
  }

  /**
   * URL 의 페이지 텍스트를 추출하여 반환한다.
   * @param {string} url - 텍스트를 추출할 웹페이지 URL
   * @returns {Promise<string>} 페이지 텍스트
   */
  async extractText(url) {
    if (!this.browser) await this.connect();

    const page = await this.browser.newPage();
    try {
      await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
      const text = await page.evaluate(() => document.body.innerText);
      return text;
    } finally {
      await page.close();
    }
  }

  /**
   * 버퍼 데이터를 workspace 경로에 저장한다.
   * @param {Buffer} data - 저장할 버퍼 데이터
   * @param {string} filePath - 저장 경로 (/workspace/ 하위)
   */
  saveToWorkspace(data, filePath) {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(filePath, data);
  }

  /**
   * browserless 연결을 종료한다.
   */
  async close() {
    if (this.browser) {
      await this.browser.close();
      this.browser = null;
    }
  }
}

// --- CLI 진입점 (단독 실행 시) ---
if (require.main === module) {
  const args = process.argv.slice(2);
  if (args.length < 2) {
    console.log('사용법: node browserless-helper.js <command> <url> [output_path]');
    console.log('  command: screenshot | pdf | text');
    console.log('  예: node browserless-helper.js screenshot https://example.com /workspace/shot.png');
    process.exit(1);
  }

  const [command, url, output] = args;
  const session = new BrowserlessSession();

  (async () => {
    try {
      if (command === 'screenshot') {
        const data = await session.screenshot(url);
        if (output) {
          session.saveToWorkspace(data, output);
          console.log(`스크린샷 저장: ${output}`);
        } else {
          process.stdout.write(data);
        }
      } else if (command === 'pdf') {
        const data = await session.printToPdf(url);
        if (output) {
          session.saveToWorkspace(data, output);
          console.log(`PDF 저장: ${output}`);
        } else {
          process.stdout.write(data);
        }
      } else if (command === 'text') {
        const text = await session.extractText(url);
        if (output) {
          fs.writeFileSync(output, text);
          console.log(`텍스트 저장: ${output}`);
        } else {
          console.log(text);
        }
      } else {
        console.error(`알 수 없는 명령: ${command}`);
        process.exit(1);
      }
    } finally {
      await session.close();
    }
  })();
}

module.exports = { BrowserlessSession };
