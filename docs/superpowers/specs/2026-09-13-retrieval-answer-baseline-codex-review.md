# Independent Codex review — retrieval and answer baseline

Reviewed artifact: `2026-09-13-retrieval-answer-baseline-design.md`  
Related: Issue #8, `docs/decisions/0001-v0.1-evidence-granularity.md`,
`evals/cases/v0.1.yaml`  
Review date: 2026-09-13

## Общая оценка

Spec пока не готов быть однозначным основанием для implementation plan. Направление разумное,
но есть четыре существенных несоответствия и несколько незаданных контрактов. Главный риск:
прогон сможет формально выдать все требуемые метрики, не измеряя качество ответа по существу.

## 1. Внутренняя согласованность и соответствие Issue #8

| Acceptance criterion Issue #8 | Оценка |
|---|---|
| Stable allowed fragment IDs, forbidden fixture never retrieved | Частично. Spec трактует fragment как whole-document ID, но Issue включает deterministic chunking и проверку chunk IDs. Это допустимо только если `none-v1` явно признан реализацией chunking для Issue #8. Сейчас это осталось неявным. |
| Citation supporting allowed fragment или abstain | Частично. Контракт проверяет наличие citation/abstain, но не определяет, как доказать, что цитируемый документ действительно поддерживает ответ и был среди retrieved/allowed документов. |
| Reproducимый eval со всеми метриками | Не определено достаточно. Нет способа расчёта groundedness и task success, фиксированных параметров, repeats, timeout и правил агрегации. |
| KEEP/REVERT/INVESTIGATE | Формулировка есть, но отсутствует правило выбора решения и применение порогов 90%/100% из framework. |
| Offline fake, никаких платных CI-вызовов | Намерение соблюдено, но fixture-механизм противоречит сценарию `provider_failure`. |

Существенные противоречия:

1. В Issue #8 deterministic chunking находится в scope, а spec исключает sub-document chunking.
   Decision 0001 был принят для Issue #7 и сам по себе не меняет acceptance criteria Issue #8.

2. Spec обещает raw provider response для всех 14 кейсов × 2 модели. Но четыре safety-кейса
   исполняются детерминированным workflow-кодом и не требуют модели. `provider_failure` означает
   timeout/error, при котором raw response может вообще отсутствовать. Фактическая топология
   live run поэтому неясна.

3. Утверждение, что document authorization filtering уже создан Issue #6, не соответствует
   текущим артефактам. Issue #6 определил доступ к заявкам, команды и role projections; в
   `data/synthetic_protected/demo-access-v1.json` нет разрешений на документы или
   forbidden-document fixture. Следовательно, первый acceptance criterion сейчас нельзя
   однозначно вывести из текста.

4. «Hard ceiling» технически несовместим с учётом стоимости только после получения response.
   Вызов, поднявший сумму выше $0.50, уже оплачен. Такой guard ограничивает дальнейшие запросы,
   но не гарантирует заявленный потолок.

Дополнительное напряжение: ключевое ожидание `missing-data-military-leave` — задать уточняющий
вопрос, однако этот признак сознательно не скорится. Поэтому «all cases» и task success могут
быть заявлены, хотя основное поведение одного кейса не проверяется.

## 2. Пробелы и неоднозначности

Implementation plan не сможет однозначно определить:

- Точную токенизацию: regex, Unicode, апострофы, Markdown/frontmatter, stemming, stopwords. Не
  задан и tie-break. Это уже не теоретика: при обычной токенизации `\w+` кейс Germany даёт
  равный overlap 9:9 для `_index.md` и `us.md`.

- Что означает «supporting citation»: достаточно ли существующего document ID, должен ли он
  входить в retrieved set и каким образом проверяется соответствие утверждений содержимому
  документа.

- Как считаются groundedness и task success. Текущий scorer умеет только evidence overlap и
  abstention; свободный текст `expected` машинно не сравнивается. Ссылка на 38-КБ документ сама
  по себе не подтверждает корректность ответа.

- Как ответ модели превращается в `refused` для prompt injection и `error_surfaced` для
  provider failure. Нужен grader или детерминированное правило, но в spec его нет.

- Форму answer contract: одно enum-поле или несколько флагов, допустимы ли одновременно
  answer+citation+abstain, что делать с неизвестной, запрещённой или не retrieved citation.

- Exact model IDs, prompt/version, параметры генерации, timeout, retry/repair policy, repeats и
  порядок вызовов. Framework требует определить их до live run.

- Как применять решение к двум моделям: отдельный verdict для каждой, один verdict для primary
  или выбор победителя. Issue говорит об одном configured live baseline; spec расширяет прогон
  до двух моделей.

- Что происходит при cutoff посередине: сохраняется ли частичный fixture/report, считается ли
  прогон валидным, как сравниваются модели при неравном числе завершённых кейсов.

- Что именно входит в `request` внутри committed fixture. Фраза «нет data-handling concern»
  слишком сильная: private repo и синтетическое имя не гарантируют, что в сериализацию не
  попадут headers, ключ, служебные поля или будущие чувствительные данные.

- Проверяется ли соответствие fixture текущим prompt hash, corpus revision и request. Без этого
  изменённый prompt может продолжать получать старый сохранённый ответ и давать ложнозелёный CI.

## 3. Риски конкретных решений

### `k=1`

При нынешнем корпусе это приемлемый baseline, но метрика сильно зависит от размера документа:
`us.md` примерно в 18 раз длиннее `_index.md` и выигрывает много overlap за счёт
общеупотребительных слов. Это скорее length/stopword bias, чем устойчивый тематический signal.

Другие риски:

- недетерминированный результат при tie;
- потеря ответа, которому нужны overview и US policy одновременно;
- zero-overlap почти бесполезен как порог релевантности для длинного документа;
- тесты из семи кейсов с одним и тем же expected document легко дадут высокий Recall@1, не
  доказывая обобщаемость retrieval.

### Hard cutoff $0.50

- Не гарантирует потолок при post-response accounting.
- Повторы запуска сбрасывают per-run budget и могут превысить общий одобренный расход.
- Порядок моделей и кейсов определяет, какая часть результатов сохранится.
- Параллельные in-flight запросы могут одновременно пересечь лимит.
- Не определено поведение при отсутствующем или запоздалом поле cost.

### Один live JSON как основа offline-тестов

- Склеивает три разные роли: экспериментальный артефакт, HTTP contract fixture и behavioral
  golden set.
- Любое изменение prompt/corpus/model требует платной полной регенерации и большого diff.
- Тесты закрепляют случайный единичный ответ модели и provider-specific JSON.
- Реальный успешный response не моделирует timeout.
- Старые ответы могут скрыть регрессию нового prompt/retrieval.
- Повреждение или несовместимость одного файла затрагивает все модели и кейсы сразу.

## 4. Очевидные нерассмотренные альтернативы

- Для retrieval: BM25/TF-IDF, нормализованный overlap, stopword filtering, минимальный relevance
  threshold либо `k=2` для текущего двухдокументного корпуса. У каждого варианта другой смысл
  метрики; spec сравнения не приводит.

- Для бюджета: pre-call reservation по worst-case output и актуальной цене модели, совмещённая
  с фактическим post-response ledger; либо отдельный per-call cap плюс общий лимит эксперимента.

- Для fixtures: разделить неизменяемый live-run artifact и небольшие вручную контролируемые
  transport/contract fixtures; timeout и malformed response хранить как отдельные синтетические
  сценарии.

- Для оценки ответов: заранее заданная human rubric, детерминированные checks по обязательным
  фактам либо отдельный зафиксированный semantic grader. Сейчас ни один вариант не выбран.

- Для provider neutrality: нейтральность задаётся интерфейсом адаптера и отдельным OpenRouter
  transport, а не самим выбором `httpx`. Spec рассматривает `httpx` против OpenAI SDK как
  архитектурную развилку, хотя это разные уровни абстракции.

## Итоговый вердикт

`INVESTIGATE` до implementation plan.

Блокирующие вопросы: согласование chunking с Issue, реальная document authorization fixture,
топология 14-кейсного прогона, метод scoring groundedness/task success и исполнимый бюджетный
контракт.
