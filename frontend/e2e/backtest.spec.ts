// 画面〜API〜計算エンジン(Python リファレンス)を通して確かめるテスト。
// 架空データ(DEMO)だけを使う。起動のしかたは playwright.config.ts。

import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

/** アクセシビリティの自動チェック(WCAG 2.1 A・AA)。違反があれば、その内容を出して失敗にする。 */
async function expectNoA11yViolations(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const summary = results.violations.map(
    (v) => `${v.id}(${v.impact}): ${v.help} — ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" / ")}`,
  );
  expect(summary, `${label} のアクセシビリティの違反`).toEqual([]);
}

async function chooseSymbol(page: Page, query: string, code: string) {
  await page.goto("/");
  await page.getByLabel("銘柄コードまたは銘柄名").fill(query);
  await page.getByRole("listitem").filter({ hasText: code }).getByRole("button").first().click();
  await expect(page.getByText("データの期間", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "この銘柄で進む" }).click();
  await expect(page.getByRole("heading", { name: /売買ルールを選ぶ/ })).toBeVisible();
  await page.getByRole("button", { name: "この売買ルールで進む" }).click();
  await expect(page.getByRole("heading", { name: /条件を決める/ })).toBeVisible();
}

async function runFromParams(page: Page) {
  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await expect(page.getByRole("heading", { name: /確認して実行する/ })).toBeVisible();
  await page.getByRole("button", { name: /バックテストを実行/ }).click();
  await expect(page.getByRole("heading", { name: "成績表" })).toBeVisible({ timeout: 30_000 });
}

test("銘柄を選んで結果まで進め、分割をまたいだ取引も正しく表示される", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/件の銘柄が見つかりました/)).toBeAttached();
  await expectNoA11yViolations(page, "手順1(銘柄)");

  await chooseSymbol(page, "ゆうなぎ", "1003");
  await expectNoA11yViolations(page, "手順3(条件)");
  // 手順が変わったら、その手順の見出しにフォーカスが移る
  await expect(page.getByRole("heading", { name: /条件を決める/ })).toBeFocused();

  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await expect(page.getByRole("heading", { name: /確認して実行する/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /手数料率/ })).toContainText("0.1%");
  await expectNoA11yViolations(page, "手順4(確認)");

  await page.getByRole("button", { name: /バックテストを実行/ }).click();
  await expect(page.getByRole("heading", { name: "成績表" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("最終資産", { exact: true })).toBeVisible();
  // DEMO:1003 は保有中に1:2分割がある。株数は「買った株数 → 売った株数」で書く
  await expect(page.getByRole("table", { name: "買いから売りまでの取引の一覧" })).toContainText("100株 → 200株");
  await expect(page.getByRole("heading", { name: "分割・併合の処理" })).toBeVisible();
  await expect(page.getByText(/架空データです/)).toBeVisible();
  // 比較の基準:同じ期間・同じ費用の買い持ち(docs/benchmark.md)。DEMO:1003 は買い持ちのほうが良かった
  await expect(page.getByText("比べると:同じ期間の買い持ちなら")).toBeVisible();
  await expect(page.getByText("2,779,717円", { exact: true })).toBeVisible();
  await expect(page.getByText("買い持ちより 98.9ポイント下")).toBeVisible();
  // 成績表にも買い持ちの値(最大ドローダウンは買い持ちのほうが大きい)
  const metricsTable = page.getByRole("region", { name: "成績表" });
  await expect(metricsTable).toContainText("買い持ち +177.97%");
  await expect(metricsTable).toContainText("買い持ち 40.98%");
  await expect(page.getByText("買い持ちの資産額(比較)")).toBeVisible();
  await expectNoA11yViolations(page, "手順5(結果)");

  // チャートはスライダーとして、キーボードで日付を動かせる
  const chart = page.getByRole("slider", { name: "チャートの日付" });
  await chart.focus();
  await page.keyboard.press("Home");
  await expect(chart).toHaveAttribute("aria-valuenow", "0");
  await expect(chart).toHaveAttribute("aria-valuetext", /^2022年1月4日/);
  await page.keyboard.press("Shift+ArrowRight");
  await expect(chart).toHaveAttribute("aria-valuenow", "20");

  // 日々の数値の表(買い持ちの資産額の列もある)。スクロールする枠は、キーボードでもスクロールできるようにフォーカスを受け取る
  // (1,000行を超える表なので、役割での検索や axe はページ全体では重い。属性で確かめる)
  await page.getByRole("button", { name: /日々の数値を表で見る/ }).click();
  const daily = page.locator('[role="region"][aria-label="日々の数値の表"]');
  await expect(daily).toHaveAttribute("tabindex", "0");
  await expect(daily.locator("thead")).toContainText("買い持ちの資産額");
});

test("入力の誤りはその欄に出て、確認へ進めない", async ({ page }) => {
  await chooseSymbol(page, "1001", "1001");
  const fee = page.getByLabel("手数料率");
  await fee.fill("-1");
  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await expect(page.getByText("手数料率とスリッページ率は0以上で入力してください")).toBeVisible();
  // 最初の誤りの欄にフォーカスが移る
  await expect(fee).toBeFocused();
  await expect(fee).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByRole("heading", { name: /条件を決める/ })).toBeVisible();

  await fee.fill("0.1");
  await expect(page.getByText("手数料率とスリッページ率は0以上で入力してください")).toHaveCount(0);
});

test("条件を変えたら前の結果には戻れず、確認の画面でそう伝える", async ({ page }) => {
  await chooseSymbol(page, "1002", "1002");
  await runFromParams(page);
  await page.getByRole("button", { name: "条件を変えて試す" }).click();
  await expect(page.getByRole("heading", { name: /条件を決める/ })).toBeVisible();
  // 条件を変える前は、手順5(結果)に移れる
  await expect(page.getByRole("button", { name: "5. 結果へ進む" })).toBeVisible();

  await page.getByLabel("スリッページ率").fill("0.2");
  await expect(page.getByRole("button", { name: "5. 結果へ進む" })).toHaveCount(0);
  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await expect(page.getByText(/前に出した結果とは条件が違います/)).toBeVisible();

  // 元の値に戻せば、また前の結果を見られる
  await page.getByRole("button", { name: "3. 条件に戻る" }).click();
  await page.getByLabel("スリッページ率").fill("0.05");
  await expect(page.getByRole("button", { name: "5. 結果へ進む" })).toBeVisible();
});

test("API の入力チェック(営業日が3日未満)は、条件の画面に戻ってその欄に出る", async ({ page }) => {
  await chooseSymbol(page, "1001", "1001");
  await page.getByLabel("開始日").fill("2026-07-30");
  await page.getByLabel("終了日").fill("2026-07-31");
  await runFromParamsExpectingError(page);
  await expect(page.getByText("期間が短すぎます。営業日が3日以上になるように指定してください")).toBeVisible();
  await expect(page.getByLabel("開始日")).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByLabel("開始日")).toBeFocused();
});

async function runFromParamsExpectingError(page: Page) {
  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await expect(page.getByRole("heading", { name: /確認して実行する/ })).toBeVisible();
  await page.getByRole("button", { name: /バックテストを実行/ }).click();
  await expect(page.getByRole("heading", { name: /条件を決める/ })).toBeVisible({ timeout: 30_000 });
}

test("総当たり:ヒートマップと検証期間の成績を見て、1マスを詳しく見る(docs/sweep.md)", async ({ page }) => {
  await chooseSymbol(page, "ゆうなぎ", "1003");
  await page.getByRole("radio", { name: /総当たりで比べる/ }).check();
  // 組み合わせの数は、入力のたびにその場で出る
  await expect(page.getByText(/組み合わせ:105通り/)).toBeVisible();
  await page.getByLabel("短期の日数の刻み").fill("0");
  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await expect(page.getByText("日数と刻みは1以上の整数で入力してください")).toBeVisible();
  await expect(page.getByLabel("短期の日数の刻み")).toBeFocused();
  await page.getByLabel("短期の日数の刻み").fill("3");
  await expectNoA11yViolations(page, "手順3(総当たりの条件)");

  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await expect(page.getByRole("heading", { name: /確認して総当たりを実行する/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /組み合わせ/ })).toContainText("105通り(計算は210回)");
  await expectNoA11yViolations(page, "手順4(総当たりの確認)");
  await page.getByRole("button", { name: /総当たりを実行/ }).click();
  await expect(page.getByRole("heading", { name: "まとめ" })).toBeVisible({ timeout: 60_000 });

  // まとめ:試した数、選ぶ期間の1位と、その検証期間での順位、順位相関(README・docs/interview.md に書いた数字)
  const summary = page.getByRole("region", { name: "まとめ" });
  await expect(summary).toContainText("105通り");
  await expect(summary).toContainText("短期24日・長期30日");
  await expect(summary).toContainText("検証期間では 105通り中 74位");
  await expect(summary).toContainText("−0.17");
  await expect(summary).toContainText("105通りで計算");
  // 買い持ちと比べる(選ぶ期間と検証期間それぞれ)
  await expect(summary).toContainText("買い持ち(比較)");
  await expect(summary).toContainText("買い持ちより良かった組み合わせ");
  // README・docs/interview.md に書いた数字:1位は検証期間で買い持ち(1.25)より悪く、検証期間で買い持ちを上回ったのは35通り
  await expect(summary).toContainText("同じ期間の買い持ち(1.25)より悪い");
  await expect(summary).toContainText("105通り中 35通り");
  // データの初日から始めたので、選ぶ期間の始まりを長期120日のウォームアップがそろう日までそろえた(docs/sweep.md 3章)
  await expect(page.getByText(/120営業日は、移動平均を作るため/)).toBeVisible();
  await expectNoA11yViolations(page, "手順5(総当たりの結果)");

  // ヒートマップはキーボードで動いて選べる(1位のマスから右へ1つ = 長期40日)
  const current = page.getByRole("grid").locator('[role=gridcell][tabindex="0"]');
  await expect(current).toHaveAttribute("aria-label", /短期24日・長期30日.*選ぶ期間の1位/);
  await current.focus();
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: /選んだ組み合わせ:短期24日・長期40日/ })).toBeVisible();
  // 色を付ける期間を検証期間に切り替えると、「確かめるためのもの」と出る
  await page.getByRole("button", { name: "検証期間", exact: true }).click();
  await expect(page.getByRole("grid")).toHaveAttribute("aria-label", /検証期間/);
  await expect(page.getByText(/検証期間の色は、選ぶ期間で選んだ組み合わせを/)).toBeVisible();

  // 検証期間だけで詳しく見る → 確認の画面から、総当たりの結果に戻る(見方はそのまま)
  await page.getByRole("button", { name: "検証期間で詳しく見る" }).click();
  await expect(page.getByRole("heading", { name: /確認して実行する/ })).toBeVisible();
  await expect(page.getByRole("row", { name: /期間/ }).first()).toContainText("2025/03/17〜2026/07/31");
  await expect(page.getByText(/総当たり\(105通り\)の中から選んだ組み合わせを、検証期間/)).toBeVisible();
  await page.getByRole("button", { name: "総当たりの結果に戻る" }).click();
  await expect(page.getByRole("heading", { name: /選んだ組み合わせ:短期24日・長期40日/ })).toBeVisible();
  await expect(page.getByRole("grid")).toHaveAttribute("aria-label", /検証期間/);

  // 選ぶ期間だけで詳しく見て実行すると、総リターンは総当たりの表の値と同じになる
  const detail = page.getByRole("table", { name: "選んだ組み合わせの、期間ごとの成績" });
  const sweepReturn = (await detail.getByRole("row", { name: /^総リターン/ }).getByRole("cell").first().innerText()).trim();
  await page.getByRole("button", { name: /選ぶ期間で詳しく見る/ }).click();
  await expect(page.getByRole("row", { name: /短期移動平均/ })).toContainText("24日");
  await expect(page.getByRole("row", { name: /長期移動平均/ })).toContainText("40日");
  await page.getByRole("button", { name: /バックテストを実行/ }).click();
  await expect(page.getByRole("heading", { name: "成績表" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/総当たり\(105通り\)の中から選んだ組み合わせを、選ぶ期間/)).toBeVisible();
  const metrics = page.getByRole("region", { name: "成績表" });
  await expect(metrics.getByText(sweepReturn, { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "総当たりの結果に戻る" }).click();
  await expect(page.getByRole("heading", { name: "まとめ" })).toBeVisible();
});

test("総当たり:列の多い格子でも、ページは横にはみ出さず、ヒートマップだけが横にスクロールする @mobile", async ({ page }) => {
  await chooseSymbol(page, "1001", "1001");
  await page.getByRole("radio", { name: /総当たりで比べる/ }).check();
  // 短期2〜3日 × 長期10〜130日(2日ごと)= 61列 × 2行 = 122通り。検証期間は使わない
  for (const [label, value] of [
    ["短期の日数の最小", "2"],
    ["短期の日数の最大", "3"],
    ["短期の日数の刻み", "1"],
    ["長期の日数の最小", "10"],
    ["長期の日数の最大", "130"],
    ["長期の日数の刻み", "2"],
  ] as const) {
    await page.getByLabel(label).fill(value);
  }
  await page.getByRole("group", { name: "検証期間の決め方" }).getByRole("button", { name: "使わない" }).click();
  await expect(page.getByText(/組み合わせ:122通り/)).toBeVisible();
  await page.getByRole("button", { name: "確認へ進む", exact: true }).click();
  await page.getByRole("button", { name: /総当たりを実行/ }).click();
  await expect(page.getByRole("heading", { name: "まとめ" })).toBeVisible({ timeout: 60_000 });

  const grid = page.getByRole("grid");
  await expect(grid).toHaveAttribute("data-size", "tiny");
  // ページ全体は横にはみ出さない。はみ出す分は、ヒートマップの枠の中だけでスクロールする
  const pageOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(pageOverflow).toBeLessThanOrEqual(0);
  const scroller = grid.locator("xpath=..");
  const sizes = await scroller.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
  expect(sizes.scroll).toBeGreaterThan(sizes.client);
  // マスは細くなりすぎない(最小6px)
  const cellWidth = await grid.locator("[role=gridcell]").first().evaluate((el) => el.getBoundingClientRect().width);
  expect(cellWidth).toBeGreaterThanOrEqual(6);

  // キーボードで右端の列へ動くと、そのマスが見えるところまで枠の中がスクロールする
  const current = grid.locator('[role=gridcell][tabindex="0"]');
  await current.focus();
  await page.keyboard.press("End");
  await expect(page.locator(":focus")).toHaveAttribute("aria-label", /長期130日/);
  expect(await scroller.evaluate((el) => el.scrollLeft)).toBeGreaterThan(0);
  await expectNoA11yViolations(page, "列の多い総当たりの結果(スマートフォン)");
});

test("スマートフォンの幅でも、取引の記録が読める @mobile", async ({ page }) => {
  await chooseSymbol(page, "あさつゆ", "1004");
  await runFromParams(page);
  // 狭い画面では、表の代わりに1取引を2行で書く一覧を出す(1:3分割をまたいだ取引)
  await expect(page.getByText(/× 100株 → 300株/)).toBeVisible();
  await expect(page.getByRole("table", { name: "買いから売りまでの取引の一覧" })).toBeHidden();
  await expectNoA11yViolations(page, "スマートフォンの結果");
});
