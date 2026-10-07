const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../public/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);

function followupButtons(markup) {
  const decode = (text) => text.replace(/&(amp|lt|gt|quot);/g, (_, entity) => ({ amp: '&', lt: '<', gt: '>', quot: '"' }[entity]));
  return [...markup.matchAll(/<button\b[^>]*class="followup-chip"[^>]*data-question="([^"]*)"[^>]*>([\s\S]*?)<\/button>/g)]
    .map((match) => ({ dataset: { question: decode(match[1]) }, textContent: decode(match[2]), disabled: false }));
}

function frontend(backstage = false, dom = {}) {
  const context = vm.createContext({ Intl, ...dom });
  const escaping = script.slice(script.indexOf('const esc ='), script.indexOf('const wrap ='));
  const presentation = script.slice(script.indexOf('const modelNames ='), script.indexOf('const mascot ='));
  const rendering = script.slice(script.indexOf('function filtered('));
  vm.runInContext(`const BACKSTAGE = ${backstage};\nlet state = null, busy = false;\n${escaping}\n${presentation}\n${rendering}`, context);
  const api = vm.runInContext('({ detectLanguage, normalizeLanguage, browserLanguage, setLanguage, publicText, beauty, culture, followupChips, bindFollowups, disableFollowups, I18N })', context);
  api.setBusy = (value) => vm.runInContext(`busy = ${Boolean(value)};`, context);
  api.boot = (languages, language) => {
    context.navigator = { languages, language };
    vm.runInContext(script.match(/^setLanguage\(browserLanguage\(navigator\.languages, navigator\.language\)\);$/m)[0], context);
  };
  const bots = [], requests = [];
  api.askWithResponse = async (message, payload) => {
    let bot;
    Object.assign(context, {
      fetch: async (_url, options) => {
        requests.push(JSON.parse(options.body));
        return { ok: true, json: async () => payload };
      },
      wrap: { querySelectorAll: () => bots.flatMap((item) => item.buttons) },
      addUser() {}, addBot: () => {
        const avatar = { innerHTML: '' };
        let markup = '';
        const body = { get innerHTML() { return markup; }, set innerHTML(value) { markup = value; bot.buttons = followupButtons(value); } };
        bot = { body, avatar, buttons: [], el: { lang: '', querySelector: (selector) => selector === '.body' ? body : avatar, querySelectorAll: () => bot.buttons }, finish() {} };
        bots.push(bot);
        return bot;
      }, bindStaff() {}, scrollDown() {},
      window: { matchMedia: () => ({ matches: false }) },
    });
    context.input.style = {};
    vm.runInContext(script.slice(script.indexOf('async function ask('), script.indexOf('function filtered(')), context);
    context.testMessage = message;
    await vm.runInContext('ask(testMessage)', context);
    bot ||= bots.at(-1);
    return { body: bot.body.innerHTML, avatar: bot.avatar.innerHTML, buttons: bot.buttons, requests, language: bot.el.lang, state: vm.runInContext('state', context) };
  };
  return api;
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

test('first visit follows the first supported browser preference', () => {
  for (const [preferences, single, expected] of [
    [['ko-KR'], 'en-US', 'ko'],
    [['en-AU'], 'ko-KR', 'en'],
    [['fr-FR', 'ja-JP', 'en-US'], 'ko-KR', 'ja'],
    [['zh-CN'], '', 'zh-Hans'],
    [['zh-SG'], '', 'zh-Hans'],
    [['zh'], '', 'zh-Hans'],
    [['zh-TW'], '', 'zh-Hant'],
    [['zh-HK'], '', 'zh-Hant'],
    [['zh-MO'], '', 'zh-Hant'],
    [['zh-Hant-HK'], '', 'zh-Hant'],
    [['zh-Hans-TW'], '', 'zh-Hans'],
    [['zh-Hant-CN'], '', 'zh-Hant'],
    [['fr-FR', 'de-DE'], 'ja-JP', 'ja'],
    [[], 'zh_TW', 'zh-Hant'],
    [undefined, 'ko-KR', 'ko'],
    [['fr-FR'], 'de-DE', 'en'],
    [undefined, undefined, 'en'],
  ]) assert.equal(ui.browserLanguage(preferences, single), expected, JSON.stringify(preferences));
});

function welcomeDOM() {
  const node = () => ({ textContent: '', innerHTML: '', dataset: {}, attributes: {}, setAttribute(key, value) { this.attributes[key] = value; } });
  const selectors = ['#hello', '#staffClose', '.brand small', '.header-note', '.composer-caption', '.eyebrow', 'h1', '.intro', '.suggest-label'];
  const nodes = Object.fromEntries(selectors.map((selector) => [selector, node()]));
  const buttons = Array.from({ length: 4 }, node);
  const document = { documentElement: { lang: 'ko' }, querySelector: (selector) => nodes[selector] };
  nodes['#hello'].querySelector = document.querySelector;
  nodes['#hello'].querySelectorAll = () => buttons;
  return { nodes, buttons, document, input: node(), send: node(), thread: node(), $: (selector, root = document) => root.querySelector(selector) };
}

for (const [language, browserTag, headline] of [
  ['ko', 'ko-KR', '나에게 맞는 뷰티,'],
  ['en', 'en-AU', 'Beauty that fits you,'],
  ['ja', 'ja-JP', '私に合うコスメ、'],
  ['zh-Hans', 'zh-CN', '适合我的美妆，'],
  ['zh-Hant', 'zh-Hant-HK', '適合我的美妝，'],
]) {
  test(`${language}: first screen and clickable examples use the browser language`, () => {
    const dom = welcomeDOM();
    const display = frontend(false, dom);
    display.boot([browserTag], 'ko-KR');
    assert.equal(dom.document.documentElement.lang, language);
    assert.ok(dom.nodes.h1.innerHTML.includes(headline));
    assert.equal(dom.input.placeholder, display.I18N[language].placeholder);
    assert.equal(dom.send.attributes['aria-label'], display.I18N[language].send);
    assert.equal(dom.nodes['.suggest-label'].textContent, display.I18N[language].welcome.suggestLabel);
    for (const [index, button] of dom.buttons.entries()) {
      const example = display.I18N[language].welcome.suggestions[index];
      assert.ok(button.innerHTML.includes(example.label));
      assert.equal(button.dataset.q, example.question);
      assert.equal(display.detectLanguage(button.dataset.q, language), language);
    }
    assert.equal(display.detectLanguage('50000', language), language);
    assert.equal(display.detectLanguage('Please reply in Japanese.', language), 'ja');
    dom.nodes['#hello'] = null;
    assert.doesNotThrow(() => display.setLanguage('ja'));
  });
}

test('citations are hidden without deleting operating hours or food restrictions', () => {
  const text = '10/10 10:00–14:00, 북문 이용 (local/notice.txt)\n땅콩·참깨 알레르기를 확인하세요 (people/food.md)';
  const shown = ui.publicText(text);
  assert.match(shown, /10:00–14:00, 북문 이용/);
  assert.match(shown, /땅콩·참깨 알레르기/);
  assert.doesNotMatch(shown, /local\/|people\//);
  assert.equal(ui.publicText('NVIDIA Nemotron /hackathon/output/demo.md', 'fallback'), 'fallback');
  assert.doesNotMatch(frontend(true).publicText(text), /local\/notice.txt/);
});

test('internal source variants disappear from visitor cards in both display modes', () => {
  const citations = [
    '(local/market_notice_2026-10-06.txt)',
    '( local/market_notice_2026-10-06.txt )',
    '(`local/market_notice_2026-10-06.txt`)',
    '（local/market_notice_2026-10-06.txt）',
    '[local/market_notice_2026-10-06.txt](local/market_notice_2026-10-06.txt)',
    '[운영 공지](local/market_notice_2026-10-06.txt)',
    '(출처: local/market_notice_2026-10-06.txt)',
    '[people/food_needs.md:L12–14]',
    '`local/market_notice_2026-10-06.txt`',
  ];
  for (const backstage of [false, true]) {
    const display = frontend(backstage);
    for (const citation of citations) {
      const text = `10/10 10:00–14:00 · 북문 이용 ${citation}\n땅콩·참깨 알레르기 확인 ${citation}`;
      const rendered = display.publicText(text);
      assert.match(rendered, /10\/10 10:00–14:00 · 북문 이용/, citation);
      assert.match(rendered, /땅콩·참깨 알레르기 확인/, citation);
      assert.doesNotMatch(rendered, /local\/|people\/|\.txt|\.md|\(\s*\)|\[\s*\]|（\s*）|`/, citation);
    }
  }
});

test('raw source names remain only in separate backstage evidence', () => {
  const source = 'local/market_notice_2026-10-06.txt';
  for (const backstage of [false, true]) {
    const rendered = frontend(backstage).culture({ turn: { language: 'ko' }, result: {
      language: 'ko', draft: `10:00–14:00 운영, 북문 이용 (${source})`,
      notices: [`북문 안내소에서 경사로 요청 ( ${source} )`],
      food_cards: `땅콩·참깨를 피해야 합니다. (\`${source}\`)`,
      uncertain: { [source]: [{ certainty: '확인 필요', sentence: '당일 경사로 사용 가능 여부를 확인해 주세요.' }] },
    } });
    const cards = rendered.split('<details class="bs"')[0];
    assert.doesNotMatch(cards, /local\/|\.txt/);
    assert.match(cards, /10:00–14:00 운영, 북문 이용/);
    assert.match(cards, /북문 안내소에서 경사로 요청/);
    assert.match(cards, /땅콩·참깨를 피해야 합니다/);
    assert.ok(rendered.includes(`<strong>${source}</strong>`));
  }
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

test('an old server language value cannot turn an English request UI back into Korean', async () => {
  const dom = welcomeDOM();
  const display = frontend(false, dom);
  display.boot(['ko-KR'], 'ko-KR');
  const result = await display.askWithResponse('I have combination skin with dullness and pores. Budget about $50 in Myeongdong and Seongsu.', {
    turn: { mode: 'beauty', language: 'ko', profile: { language: 'ko', skin_type: 'combination', concerns: ['dullness', 'pores'], avoid_ingredients: ['fragrance', 'alcohol'], budget_krw: 67500, areas: ['명동', '성수'] } },
    result: { language: 'ko', summary: 'Compare the products before buying.', staff_card: '매장 직원에게 보여주세요.', authenticity_checks: [{ target: 'K-Skin Mask', trusted: false }] },
  });
  assert.equal(dom.document.documentElement.lang, 'en');
  assert.equal(dom.nodes['.header-note'].textContent, 'Your beauty day');
  assert.equal(dom.nodes['.brand small'].textContent, 'Your gate to authentic K-beauty');
  assert.match(result.avatar, /Your K-BeautyGate/);
  assert.equal(result.language, 'en');
  assert.equal(result.state.language, 'en');
  for (const label of ['Combination skin', 'Dullness', 'Pores', 'Avoid fragrance', 'Avoid alcohol', 'Myeongdong', 'Seongsu', 'Please check before you buy']) assert.ok(result.body.includes(label));
  assert.doesNotMatch(result.body, /복합성 피부|칙칙함|향료 제외|구매 전에 한 번 더/);
});

function visitorCards(markup) {
  return markup.split('<details class="bs"')[0]
    .replace(/<div class="staff"[^>]*>[\s\S]*?<\/div>/g, '')
    .replace(/<small class="route-original" lang="ko">[\s\S]*?<\/small>/g, '')
    .replace(/<small class="bs">[\s\S]*?<\/small>/g, '');
}

for (const [language, translatedPlace, translatedConcern, translatedIngredient] of [
  ['en', 'Beauty Square Myeongdong', 'Skin tightness', 'Essential oils'],
  ['ja', 'ビューティースクエア明洞店', '肌のつっぱり', 'エッセンシャルオイル'],
  ['zh-Hans', '美妆广场明洞店', '肌肤紧绷', '精油'],
  ['zh-Hant', '美妝廣場明洞店', '肌膚緊繃', '精油'],
]) {
  test(`${language}: translated route names precede Korean originals while other visitor labels stay localized`, () => {
    const result = {
      recommendations: [{ rank: 1, name_ko: '하루담 토너', name: 'Harudam Toner', price_krw: 18000 }],
      route: [{ time: '13:00', name: '뷰티스퀘어 명동점', area: '명동' }],
      staff_card: '뷰티스퀘어 명동점에서 하루담 토너를 찾고 있어요.',
      localized: { language, summary: explanations[language][0] + ' 뷰티스퀘어 명동점',
        recommendation_reasons: [[explanations[language][1]]], route_notes: [explanations[language][1]],
        notices: [explanations[language][2]], display_names: { '뷰티스퀘어 명동점': translatedPlace, '당김': translatedConcern, '에센셜오일': translatedIngredient } },
    };
    const markup = ui.beauty({ turn: { language, profile: { skin_type: 'combination', concerns: ['당김'], avoid_ingredients: ['에센셜오일'], areas: ['명동'] } }, result });
    const visible = visitorCards(markup);
    assert.doesNotMatch(visible, /[\u3131-\u318e\uac00-\ud7a3]/);
    for (const label of [translatedPlace, translatedConcern, translatedIngredient, 'Harudam Toner']) assert.ok(visible.includes(label));
    const route = markup.match(/<ul class="route">([\s\S]*?)<\/ul>/)[1];
    const original = '<small class="route-original" lang="ko">뷰티스퀘어 명동점</small>';
    assert.ok(route.includes(original));
    assert.ok(route.indexOf(translatedPlace) < route.indexOf(original));
    assert.ok(route.indexOf(original) < route.indexOf(explanations[language][1]));
    assert.equal((route.match(/뷰티스퀘어 명동점/g) || []).length, 1);
    assert.match(markup, /뷰티스퀘어 명동점에서 하루담 토너를 찾고 있어요/);
  });
}

test('missing or malformed translations retain Korean route originals below localized fallbacks', () => {
  const markup = ui.beauty({ turn: { language: 'en', profile: { concerns: ['당김'], avoid_ingredients: ['에센셜오일'], areas: ['새로운 지역'] } }, result: {
    recommendations: [{ rank: 1, name_ko: '토너 원문', price_krw: 10000 }],
    route: [{ time: '13:00', name: '매장 원문', area: '새로운 지역' },
      { time: '14:00', name: '번역 없는 체험', kind: 'experience', area: '명동' }],
    localized: { language: 'en', display_names: { '매장 원문': '아직 한국어인 표시명' } },
    staff_card: '직원용 한국어는 남깁니다.',
  } });
  const visible = visitorCards(markup);
  assert.doesNotMatch(visible, /[\u3131-\u318e\uac00-\ud7a3]/);
  assert.match(visible, /Translation needed/);
  const route = markup.match(/<ul class="route">([\s\S]*?)<\/ul>/)[1];
  const stops = [...route.matchAll(/<li>([\s\S]*?)<\/li>/g)].map((match) => match[1]);
  for (const [index, name] of ['매장 원문', '번역 없는 체험'].entries()) {
    const original = `<small class="route-original" lang="ko">${name}</small>`;
    const fallback = `${ui.I18N.en.place} · ${ui.I18N.en.translationPending}`;
    assert.ok(stops[index].includes(original));
    assert.ok(stops[index].includes(fallback));
    assert.ok(stops[index].indexOf(fallback) < stops[index].indexOf(original));
  }
  assert.match(markup, /직원용 한국어는 남깁니다/);
});

test('Korean routes and names without Korean do not add a duplicate original row', () => {
  for (const language of ['ko', 'en']) {
    const markup = ui.beauty({ turn: { language, profile: {} }, result: {
      route: [{ name: '가상 팝업', kind: 'popup' }, { name: 'Mock Beauty Lounge' }],
      localized: { language, display_names: { '가상 팝업': 'Mock Pop-up' } },
    } });
    const route = markup.match(/<ul class="route">([\s\S]*?)<\/ul>/)[1];
    assert.equal((route.match(/class="route-original"/g) || []).length, language === 'ko' ? 0 : 1);
    assert.equal((route.match(/가상 팝업/g) || []).length, 1);
    assert.equal((route.match(/Mock Beauty Lounge/g) || []).length, 1);
  }
});

test('route original rows remove internal citations and escape HTML in both display modes', () => {
  const original = '<b>가상 팝업</b> & "체험"';
  const translated = 'Mock <b>Pop-up</b> & "Experience"';
  for (const backstage of [false, true]) {
    const markup = frontend(backstage).beauty({ turn: { language: 'en', profile: {} }, result: {
      route: [{ name: `${original} (\`local/mock_place.md\`)`, kind: 'experience' }],
      localized: { language: 'en', display_names: { [original]: translated } },
    } });
    const route = markup.match(/<ul class="route">([\s\S]*?)<\/ul>/)[1];
    assert.ok(route.includes('Mock &lt;b&gt;Pop-up&lt;/b&gt; &amp; &quot;Experience&quot;'));
    assert.ok(route.includes('<small class="route-original" lang="ko">&lt;b&gt;가상 팝업&lt;/b&gt; &amp; &quot;체험&quot;</small>'));
    assert.doesNotMatch(route, /local\/|mock_place\.md|<b>/);
  }
});

test('followup chips preserve all five languages and keep source labels backstage', () => {
  const questions = {
    ko: '예산을 40,000원으로 바꾸면 어떤가요?',
    en: 'What if my budget is 40,000 won?',
    ja: '予算を40,000ウォンにしたら？',
    'zh-Hans': '预算改为40,000韩元，可以吗？',
    'zh-Hant': '預算改為40,000韓元，可以嗎？',
  };
  for (const [language, question] of Object.entries(questions)) {
    for (const backstage of [false, true]) {
      const display = frontend(backstage);
      const markup = display.followupChips([{ text: question, source: 'rule' }, { text: question, source: 'nemotron' }], language);
      const buttons = followupButtons(markup);
      assert.equal(buttons.length, 2);
      for (const button of buttons) {
        assert.equal(button.dataset.question, question);
        assert.equal(button.textContent, question);
      }
      assert.ok(display.I18N[language].followups);
      assert.ok(markup.includes(display.I18N[language].followups));
      assert.match(markup, /<span class="bs followup-source">rule<\/span>/);
      assert.match(markup, /<span class="bs followup-source">nemotron<\/span>/);
      assert.doesNotMatch(markup.replace(/<span class="bs followup-source">[\s\S]*?<\/span>/g, ''), /rule|nemotron/);
    }
  }
});

test('empty or malformed suggestions vanish and technical questions are omitted individually', () => {
  for (const suggestions of [undefined, null, '', {}, [], [null, false, 3, 'question', {}, { text: 3 }, { text: '' }, { text: '   ' }]]) {
    assert.equal(ui.followupChips(suggestions, 'en'), '');
  }
  const display = frontend();
  display.beauty({ turn: { language: 'en' }, result: { nvidia: { chat_model: 'mock-private-model-v1' } } });
  const question = '  Can I compare "cream" & <gel>?  ';
  const markup = display.followupChips([
    { text: 'Show OpenShell details', source: 'rule' },
    { text: 'Use local/mock_data.md', source: 'rule' },
    { text: 'Try MOCK-PRIVATE-MODEL-V1', source: 'nemotron' },
    { text: question, source: '<script>unsafe</script>' },
  ], 'en');
  const buttons = followupButtons(markup);
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].dataset.question, question);
  assert.equal(buttons[0].textContent, question);
  assert.match(markup, /&quot;cream&quot; &amp; &lt;gel&gt;/);
  assert.doesNotMatch(markup, /<gel>|<script>|unsafe|OpenShell|mock_data|PRIVATE-MODEL|followup-source/);
});

test('followup clicks send the exact original question and ignore busy or disabled buttons', () => {
  const question = '원문 "질문" & <도움>';
  const buttons = [{ dataset: { question }, disabled: false }, { dataset: { question: 'older question' }, disabled: true }];
  const sent = [];
  const querySelectorAll = (selector) => { assert.equal(selector, '.followup-chip'); return buttons; };
  const display = frontend(false, { ask: (text) => sent.push(text), wrap: { querySelectorAll } });
  display.bindFollowups({ querySelectorAll });
  buttons[0].onclick();
  assert.deepEqual(sent, [question]);
  display.setBusy(true);
  buttons[0].onclick();
  display.setBusy(false);
  buttons[1].onclick();
  assert.deepEqual(sent, [question]);
  display.disableFollowups();
  assert.ok(buttons.every((button) => button.disabled));
  buttons[0].onclick();
  assert.deepEqual(sent, [question]);
});

test('only the latest answer has active followups, including empty suggestions and failed requests', async () => {
  const display = frontend(false, welcomeDOM());
  display.boot(['en-US'], 'en-US');
  const response = (mode, suggestions) => ({ turn: { mode, language: 'en', profile: {} }, result: {
    suggestions, localized: { language: 'en', summary: 'Your beauty choices.', draft: 'Your cultural route.' },
  } });
  const first = await display.askWithResponse('Please recommend a beauty route.', response('beauty', [{ text: 'Make it cheaper.', source: 'rule' }]));
  assert.equal(first.buttons.length, 1);
  assert.equal(first.buttons[0].disabled, false);
  assert.equal(typeof first.buttons[0].onclick, 'function');
  assert.ok(first.body.trimEnd().endsWith(display.followupChips([{ text: 'Make it cheaper.', source: 'rule' }], 'en')));
  await display.askWithResponse('   ', {});
  assert.equal(first.buttons[0].disabled, false);
  assert.equal(first.requests.length, 1);

  const secondPending = display.askWithResponse('Please show a cultural route.', response('culture', [{ text: 'Use the wheelchair route.', source: 'nemotron' }]));
  assert.equal(first.buttons[0].disabled, true);
  const second = await secondPending;
  assert.equal(second.buttons.length, 1);
  assert.equal(second.buttons[0].disabled, false);
  assert.equal(typeof second.buttons[0].onclick, 'function');
  assert.ok(second.body.trimEnd().endsWith(display.followupChips([{ text: 'Use the wheelchair route.', source: 'nemotron' }], 'en')));
  const third = await display.askWithResponse('Please shorten it.', response('culture', undefined));
  assert.equal(third.buttons.length, 0);
  assert.equal(first.buttons[0].disabled, true);
  assert.equal(second.buttons[0].disabled, true);

  const fourth = await display.askWithResponse('Please recommend another beauty route.', response('beauty', [{ text: 'Check the opening hours.', source: 'rule' }]));
  assert.equal(fourth.buttons[0].disabled, false);
  const failed = await display.askWithResponse('Please check the hours.', { error: 'Synthetic response failure' });
  assert.match(failed.body, /role="alert"/);
  assert.equal(failed.buttons.length, 0);
  assert.equal(first.buttons[0].disabled, true);
  assert.equal(second.buttons[0].disabled, true);
  assert.equal(fourth.buttons[0].disabled, true);
  const requestCount = failed.requests.length;
  for (const button of [...first.buttons, ...second.buttons, ...fourth.buttons]) button.onclick();
  assert.equal(failed.requests.length, requestCount);
});

test('the gate remains decorative, with translated status and reduced-motion support', () => {
  assert.match(script, /class="friendly" role="status"/);
  assert.match(script, /class="loading-gate" aria-hidden="true"/);
  assert.match(html, /prefers-reduced-motion: reduce/);
  assert.match(html, /\.bs \{ display: none !important; \}/);
  assert.match(script, /get\("backstage"\) === "1"/);
});
