// 토끼 채팅 화면(public/bunny.html) 검사: 배포 데모 응답을 그려도 개발 용어·경로가 화면에 나오지 않는지 확인합니다.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '../public/bunny.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const context = vm.createContext({ Intl, URLSearchParams, console });
vm.runInContext(script, context); // document가 없으므로 boot()는 실행되지 않습니다
const ui = vm.runInContext('({ renderResult, cleanText, safetyView, planView, cardsView, I18N })', context);
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/bunny', `${name}.json`), 'utf8'));
const visible = (markup) => markup.replace(/<[^>]*>/g, ' ').replace(/&[a-z#0-9]+;/g, ' ');
const FORBIDDEN = /restricted|secrets?\b|\/hackathon|\.csv|\.jsonl?|\.txt\b|\.md\b|DENIED|OpenShell|Nemotron|NVIDIA|sandbox|prompt.?injection|\btoken|\bAPI\b|접근 금지|비밀 정보|토큰|샌드박스|customer_list|example\.net|비자기회귀|Jev/i;

test('self-contained: no external scripts, styles or images', () => {
  assert.doesNotMatch(html, /<script\s+src=|<link\s+rel="stylesheet"|src="https?:/i);
  assert.match(html, /const ART = \{"card":"data:image\/webp;base64,/);
});

for (const name of ['ja', 'en', 'culture', 'attack', 'zh']) {
  test(`${name}: rendered answer has no technical terms or file paths`, () => {
    const data = fixture(name);
    const markup = ui.renderResult(data, `test-${name}`);
    assert.doesNotMatch(visible(markup), FORBIDDEN);
    for (const view of [ui.safetyView, ui.planView, ui.cardsView]) assert.doesNotMatch(visible(view(data.turn.language)), FORBIDDEN);
  });
}

test('attack: refusals are explained in plain words and hidden requests are counted', () => {
  const data = fixture('attack');
  const text = visible(ui.renderResult(data, 'test-attack-ko'));
  assert.match(text, /보호된 자료는 열어 보지 않았어요/);
  assert.match(text, /메시지나 메일은 보내지 않았어요/);
  assert.match(text, /수상한 부탁 \d+건은 따르지 않았어요/);
  assert.match(text, /매장 직원에게 보여주세요/);
});

test('cleanText drops file citations but keeps the notice', () => {
  assert.equal(ui.cleanText('뷰티스퀘어 성수점: 2026-10-07 14:00 조기 마감 (beauty/stores/store_notice_2026-10-06.txt)'), '뷰티스퀘어 성수점: 2026-10-07 14:00 조기 마감');
  assert.equal(ui.cleanText('I did not open the restricted area. Nothing was sent.'), 'Nothing was sent.');
});
