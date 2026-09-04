// [Flow: Step 1 (DOM/전역 초기화) -> Step 2 (loadPaddle 호출) -> Step 3 (script 주입/중복/실패 동작 검증)]
import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

const PADDLE_SDK_URL = "https://cdn.paddle.com/paddle/v2/paddle.js";

/** 모듈 레벨 캐시를 비우기 위해 매 테스트마다 새로 import 한다. */
async function freshModule() {
  vi.resetModules();
  return import("./loadPaddle.js");
}

function injectedScript() {
  return document.querySelector(`script[src="${PADDLE_SDK_URL}"]`);
}

describe("loadPaddle", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
    delete window.Paddle;
  });

  afterEach(() => {
    delete window.Paddle;
  });

  it("이미 로드돼 있으면 스크립트를 주입하지 않는다", async () => {
    window.Paddle = { Initialize: vi.fn() };
    const { loadPaddle } = await freshModule();

    await expect(loadPaddle()).resolves.toBe(window.Paddle);
    expect(injectedScript()).toBeNull();
  });

  it("script load 후 window.Paddle 로 resolve 한다", async () => {
    const { loadPaddle } = await freshModule();
    const promise = loadPaddle();

    const script = injectedScript();
    expect(script).not.toBeNull();
    expect(script.async).toBe(true);

    window.Paddle = { Initialize: vi.fn() };
    script.dispatchEvent(new Event("load"));

    await expect(promise).resolves.toBe(window.Paddle);
  });

  it("동시 호출은 스크립트를 한 번만 주입한다", async () => {
    const { loadPaddle } = await freshModule();
    const a = loadPaddle();
    const b = loadPaddle();

    expect(document.querySelectorAll(`script[src="${PADDLE_SDK_URL}"]`)).toHaveLength(1);

    window.Paddle = { Initialize: vi.fn() };
    injectedScript().dispatchEvent(new Event("load"));

    expect(await a).toBe(window.Paddle);
    expect(await b).toBe(window.Paddle);
  });

  it("로드 실패 시 null 로 resolve 한다 (호출부가 checkout_url 폴백을 쓴다)", async () => {
    const { loadPaddle } = await freshModule();
    const promise = loadPaddle();

    injectedScript().dispatchEvent(new Event("error"));

    await expect(promise).resolves.toBeNull();
  });
});

describe("initPaddle", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
    delete window.Paddle;
  });

  it("로드된 SDK 에 토큰으로 Initialize 를 호출한다", async () => {
    const Initialize = vi.fn();
    window.Paddle = { Initialize };
    const { initPaddle } = await freshModule();

    const paddle = await initPaddle("tok_test");

    expect(paddle).toBe(window.Paddle);
    expect(Initialize).toHaveBeenCalledWith({ token: "tok_test" });
  });

  it("Initialize 가 던져도 SDK 를 그대로 반환한다 (중복 초기화는 무해)", async () => {
    window.Paddle = {
      Initialize: vi.fn(() => {
        throw new Error("already initialized");
      }),
    };
    const { initPaddle } = await freshModule();

    await expect(initPaddle("tok_test")).resolves.toBe(window.Paddle);
  });

  it("SDK 로드에 실패하면 null 을 반환한다", async () => {
    const { initPaddle } = await freshModule();
    const promise = initPaddle("tok_test");

    injectedScript().dispatchEvent(new Event("error"));

    await expect(promise).resolves.toBeNull();
  });
});
