const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);

function frontend(backstage = false) {
  const context = vm.createContext({ Intl });
  const escaping = script.slice(script.indexOf('const esc ='), script.indexOf('const wrap ='));
  const presentation = script.slice(script.indexOf('const modelNames ='), script.indexOf('const mascot ='));
  const rendering = script.slice(script.indexOf('function filtered('));
  vm.runInContext(`const BACKSTAGE = ${backstage};\n${escaping}\n${presentation}\n${rendering}`, context);
  return vm.runInContext('({ detectLanguage, normalizeLanguage, publicText, beauty, culture, I18N })', context);
}

const ui = frontend();
const cases = [
  ['건성 피부에 맞는 화장품을 추천해 주세요.', null, 'ko'],
  ['I have dry skin near 성수 and 명동.', null, 'en'],
  ['敏感肌です。明洞でコスメを探しています。', null, 'ja'],
  ['我想在명동买保湿产品。', null, 'zh-Hans'],
  ['我想在명동買保濕產品。', null, 'zh-Hant'],
  ['好，明洞。', 'zh-Hant', 'zh-Hant'],
  ['50000', 'ja', 'ja'],
  ['OK', 'zh-Hant', 'zh-Hant'],
  ['Please make it cheaper.', 'ja', 'en'],
  ['더 싸게', 'en', 'ko'],
  ['비싸요', 'en', 'ko'],
  ['가격은?', 'ja', 'ko'],
  ['명동', 'ja', 'ja'],
  ['我想購物', 'en', 'zh-Hant'],
  ['我想购物', 'zh-Hant', 'zh-Hans'],
  ['更短一些', 'en', 'zh-Hans'],
  ['Please reply in Traditional Chinese.', 'en', 'zh-Hant'],
  ['Please answer in Simplified Chinese.', 'zh-Hant', 'zh-Hans'],
  ['영어로 답해 주세요.', 'ko', 'en'],
  ['日本語でお願いします。', 'en', 'ja'],
  ['請用繁體中文回答。', 'en', 'zh-Hant'],
  ['请用简体中文回答。', 'zh-Hant', 'zh-Hans'],
  ['한국어로 대답해 주세요.', 'en', 'ko'],
  ['Translate this into English, then reply in Japanese.', 'ko', 'ja'],
  ['I want the Traditional Chinese product label checked.', 'en', 'en'],
];

for (const [message, previous, expected] of cases) {
  test(`request language: ${message}`, () => assert.equal(ui.detectLanguage(message, previous), expected));
}

test('legacy Chinese language tags select the right writing system', () => {
  assert.equal(ui.normalizeLanguage('zh'), 'zh-Hans');
  assert.equal(ui.normalizeLanguage('zh_TW'), 'zh-Hant');
  assert.equal(ui.normalizeLanguage('zh-HK'), 'zh-Hant');
  assert.equal(ui.normalizeLanguage('zh-CN'), 'zh-Hans');
});

test('citations are hidden without deleting operating hours or food restrictions', () => {
  const text = '10/10 10:00–14:00, 북문 이용 (local/notice.txt)\n땅콩·참깨 알레르기를 확인하세요 (people/food.md)';
  const shown = ui.publicText(text);
  assert.match(shown, /10:00–14:00, 북문 이용/);
  assert.match(shown, /땅콩·참깨 알레르기/);
  assert.doesNotMatch(shown, /local\/|people\//);
  assert.equal(ui.publicText('NVIDIA Nemotron /hackathon/output/demo.md', 'fallback'), 'fallback');
  assert.match(frontend(true).publicText(text), /local\/notice.txt/);
});

const explanations = {
  ko: ['촉촉한 하루를 준비했어요.', '제형을 확인해 주세요.', '방문 전에 시간을 확인해 주세요.', '1910년과 1919년은 확인이 필요해요.'],
  en: ['Your beauty day is ready.', 'Compare the textures in store.', 'Confirm the opening hours before visiting.', 'The dates 1910 and 1919 need confirmation.'],
  ja: ['あなたの旅を準備しました。', 'お店で使用感を確認してください。', '訪問前に営業時間を確認してください。', '1910年と1919年は確認が必要です。'],
  'zh-Hans': ['你的美妆之旅准备好了。', '请在店内确认质地。', '请在到访前确认营业时间。', '1910年与1919年仍需确认。'],
  'zh-Hant': ['你的美妝之旅準備好了。', '請在店內確認質地。', '請在到訪前確認營業時間。', '1910年與1919年仍需確認。'],
};

for (const [language, [summary, reason, notice, caveat]] of Object.entries(explanations)) {
  test(`${language}: translated details, Korean staff card and safe missing price`, () => {
    const turn = { mode: 'beauty', language, profile: { language, skin_type: 'dry', areas: ['명동'] } };
    const result = {
      language,
      summary: '한국어 원본 설명',
      recommendations: [{ rank: 1, name: 'Dew Cream', why: ['한국어 원본 추천 이유'] }],
      route: [{ time: '14:00', name: 'Beauty Studio', area: '명동', note: '한국어 원본 동선' }],
      notices_applied: ['한국어 원본 공지'],
      staff_card: '안녕하세요! 향료를 피하고 싶어요.',
      localized: { language, status: 'ready', summary, recommendation_reasons: [[reason]], route_notes: [reason], notices: [notice], caveats: [caveat] },
    };
    const rendered = ui.beauty({ turn, result });
    for (const expected of [summary, reason, notice, caveat, ui.I18N[language].picks, ui.I18N[language].priceUnknown]) assert.ok(rendered.includes(expected));
    assert.doesNotMatch(rendered, /한국어 원본/);
    assert.match(rendered, /lang="ko"/);
    assert.ok(rendered.includes(`data-language="${language}"`));
    assert.match(rendered, /안녕하세요! 향료를 피하고 싶어요/);
    assert.doesNotMatch(rendered, /[₩￥]0/);

    const cultural = ui.culture({ turn: { ...turn, mode: 'culture' }, result: {
      language, visit_date: '2026-10-10', draft: '한국어 원본 설명', food_cards: '땅콩과 참깨를 피해야 합니다.',
      localized: { language, draft: summary, notices: [notice], caveats: [caveat] },
    } });
    for (const expected of [summary, notice, caveat, ui.I18N[language].culture]) assert.ok(cultural.includes(expected));
    assert.match(cultural, /땅콩과 참깨를 피해야 합니다/);
    assert.doesNotMatch(cultural, /한국어 원본/);
  });
}

test('a mismatched locale payload does not appear as a successful English answer', () => {
  const rendered = ui.beauty({ turn: { language: 'en', profile: {} }, result: {
    summary: '한국어 원본 설명입니다.', localized: { language: 'ko', summary: '한국어 번역 설명입니다.' },
  } });
  assert.doesNotMatch(rendered, /한국어 (?:원본|번역) 설명/);
  assert.ok(rendered.includes(ui.I18N.en.reply));
});

test('the gate remains decorative, with translated status and reduced-motion support', () => {
  assert.match(script, /class="friendly" role="status"/);
  assert.match(script, /class="loading-gate" aria-hidden="true"/);
  assert.match(html, /prefers-reduced-motion: reduce/);
  assert.match(html, /\.bs \{ display: none !important; \}/);
  assert.match(script, /get\("backstage"\) === "1"/);
});
