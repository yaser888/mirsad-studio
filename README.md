# Mirsad Agent

وكيل ذكاء اصطناعي متعدد الخطوات يعمل من الطرفية، مع أدوات تنفيذ حقيقية، ذاكرة جلسات دائمة، ودعم خمسة مزوّدي نماذج (OpenAI, Anthropic, OpenRouter, DeepSeek, Groq) بالإضافة إلى Ollama المحلي.

A multi-step AI agent CLI with real tools, persistent sessions, and multi-provider LLM support.

---

## المزايا

- **حلقة وكيل متعددة الخطوات**: يخطّط، ينفّذ الأدوات، يقرأ النتائج، ويعدّل خطته حتى إنجاز المهمة.
- **أدوات حقيقية**: قراءة/كتابة/تعديل الملفات، البحث في الكود، تنفيذ أوامر PowerShell/bash، جلب صفحات الويب، والبحث في الويب.
- **ذاكرة دائمة**: كل جلسة تُحفظ تلقائياً في `~/.mirsad/sessions/` ويمكن استئنافها لاحقاً.
- **عدة مزوّدين**: OpenAI وAnthropic وOpenRouter وDeepSeek وGroq وOllama المحلي — بتبديل فوري.
- **حواجز أمان**: كل أمر shell أو كتابة ملف يتطلب موافقتك افتراضياً، مع حظر الأوامر المدمّرة للنظام.
- **حدود واضحة**: سقف خطوات، تقليم سياق المحادثة، وحدود لحجم المخرجات.
- **واجهة عربية/إنجليزية**: الوكيل يرد بلغة رسالتك.

---

## المتطلبات

- Python **3.10+** (تم اختباره على 3.14)
- PowerShell على Windows أو bash على Linux/macOS
- مفتاح API لأحد المزوّدين، أو Ollama محلي

---

## التثبيت السريع (Windows)

```powershell
cd C:\Users\سكواد\mirsad-agent

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .

mirsad init
```

إذا منع PowerShell تنشيط البيئة:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

أو شغّل الأمر مباشرة دون تنشيط:

```powershell
.\.venv\Scripts\mirsad.exe init
```

### إضافة مفاتيح API

```powershell
notepad $HOME\.mirsad\.env
```

املأ المفتاح الذي ستستخدمه فقط:

```dotenv
OPENAI_API_KEY=sk-...
# أو
ANTHROPIC_API_KEY=sk-ant-...
# أو
OPENROUTER_API_KEY=sk-or-...
# أو
DEEPSEEK_API_KEY=sk-...
# أو
GROQ_API_KEY=gsk_...
```

للنموذج المحلي:

```powershell
ollama pull qwen2.5:7b
mirsad chat --provider ollama --model qwen2.5:7b
```

### التشغيل دون تثبيت

```powershell
pip install httpx rich
python -m mirsad
```

---

## الاستخدام

```powershell
mirsad init                         # إنشاء مجلد الإعدادات
mirsad chat                         # جلسة تفاعلية جديدة
mirsad chat -s 20261105-153045-a1b2 # استئناف جلسة
mirsad ask "افحص هذا المشروع وشغّل الاختبارات"
mirsad ask "كم عدد ملفات Python؟" --quiet
mirsad sessions list
mirsad sessions show <id>
mirsad tools
mirsad providers
mirsad config
```

### جلسة تفاعلية

```
$ mirsad chat

MIRSAD AGENT
provider  openai / gpt-4o-mini
workspace C:\Users\سكواد\mirsad-agent
session   20261105-153045-a1b2

You › أضف ملف README وقم بتشغيل الاختبارات
```

أوامر داخل الجلسة:

| الأمر | الوظيفة |
|---|---|
| `/help` | عرض المساعدة |
| `/exit` أو `/quit` | حفظ وخروج |
| `/session` | تفاصيل الجلسة وملفها |
| `/plan` | الخطة الحالية |
| `/tools` | الأدوات المتاحة |
| `/workdir [path]` | عرض/تغيير مجلد العمل |
| `/model [name]` | عرض/تغيير النموذج |
| `/provider [id]` | عرض/تغيير المزوّد |
| `/yes` | تشغيل/إيقاف الموافقة التلقائية |
| `/clear` | مسح سجل المحادثة |
| `/new` | بدء جلسة جديدة |

---

## المزوّدون

| المزوّد | متغيّر المفتاح | النموذج الافتراضي |
|---|---|---|
| `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-4-20250514` |
| `openrouter` | `OPENROUTER_API_KEY` | `openai/gpt-4o-mini` |
| `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| `groq` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` |
| `ollama` | لا يحتاج مفتاحاً | `qwen2.5:7b` |

اختر مزوّداً افتراضياً:

```powershell
mirsad chat --provider deepseek
$env:MIRSAD_PROVIDER = "openai"
```

يمكن تجاوز عنوان الـ API عبر `MIRSAD_BASE_URL`، ومفتاح عام عبر `MIRSAD_API_KEY` (مفيد لخدمات متوافقة مع OpenAI).

---

## الأدوات

| الأداة | تحتاج موافقة | الوظيفة |
|---|---|---|
| `read_file` | لا | قراءة ملف نصي بأرقام الأسطر |
| `write_file` | نعم | إنشاء/استبدال ملف |
| `edit_file` | نعم | استبدال نص فريد داخل ملف |
| `list_files` | لا | استكشاف الملفات والمجلدات |
| `search_text` | لا | بحث نصي/Regex مع رقم السطر |
| `run_command` | نعم | تنفيذ PowerShell/bash وجمع الخرج |
| `web_search` | لا | بحث ويب (Tavily أو DuckDuckGo) |
| `web_fetch` | لا | جلب صفحة عامة وتحويلها لنص |
| `update_plan` | لا | عرض/تحديث خطة المهمة |

الأدوات محصورة داخل مجلد العمل: أي مسار خارجه يُرفض. كما تُحظر أوامر مثل `rm -rf /` و`format C:` و`diskpart` و`shutdown` حتى مع الموافقة.

الموافقة الافتراضية لكل جلسة يمكن تعطيلها بـ `-y/--yes` (بحذر)، أو تبديلها داخل الجلسة بـ `/yes`.

### إعداد البحث في الويب

- افتراضياً يستخدم **DuckDuckGo** دون مفتاح.
- للحصول على نتائج أكثر موثوقية، ضع مفتاح Tavily في `~/.mirsad/.env`:

```dotenv
TAVILY_API_KEY=tvly-...
```

---

## الإعدادات

ملف الإعدادات: `~/.mirsad/config.json`

```json
{
  "provider": "openai",
  "model": null,
  "temperature": 0.2,
  "max_steps": 12,
  "max_history": 80,
  "auto_approve": false,
  "workdir": null
}
```

الأولوية: **خيارات سطر الأوامر > متغيرات البيئة > config.json**.

متغيرات البيئة المدعومة:

```
MIRSAD_PROVIDER, MIRSAD_MODEL, MIRSAD_TEMPERATURE, MIRSAD_MAX_STEPS,
MIRSAD_MAX_HISTORY, MIRSAD_AUTO_APPROVE, MIRSAD_BASE_URL, MIRSAD_API_KEY,
MIRSAD_HOME, OLLAMA_BASE_URL, TAVILY_API_KEY
```

`MIRSAD_HOME` يغيّر مجلد الإعدادات والجلسات (افتراضياً `~/.mirsad`).

---

## كيف يعمل الوكيل؟

1. تُضاف رسالتك إلى الجلسة وتُحفظ.
2. يُرسل النظام + سجل المحادثة + تعريف الأدوات إلى النموذج.
3. إذا طلب النموذج أدوات، تُنفّذ (بعد موافقتك عند الحاجة) وتُضاف النتائج.
4. تتكرر الحلقة حتى يرد النموذج دون أدوات أو ينفد سقف الخطوات.
5. عند بلوغ السقف، يُطلب من النموذج تلخيص ما أُنجز وما تبقّى دون تنفيذ أدوات إضافية.

سقف الخطوات الافتراضي 12، ويمكن تغييره بـ `--max-steps`. يُقلَّم السياق المُرسل إلى آخر 80 رسالة (`--max-history`) مع الحفاظ على اقتران نتائج الأدوات بنداءاتها.

---

## هيكل المشروع

```
mirsad-agent/
├── mirsad/
│   ├── __main__.py          # python -m mirsad
│   ├── cli.py               # أوامر CLI والجلسة التفاعلية
│   ├── agent.py             # حلقة plan → act → observe
│   ├── config.py            # الإعدادات و.env
│   ├── memory.py            # الجلسات والتقليم
│   ├── prompts.py           # موجه النظام
│   ├── ui.py                # واجهة Rich
│   ├── providers/
│   │   ├── base.py          # الواجهة المشتركة والأخطاء
│   │   ├── openai_compat.py # OpenAI/OpenRouter/DeepSeek/Groq/Ollama
│   │   ├── anthropic.py     # تحويل رسائل Anthropic الأصلية
│   │   └── factory.py       # إنشاء المزوّد
│   └── tools/
│       ├── registry.py      # التسجيل والتحقق والموافقة
│       ├── files.py         # الملفات والأوامر
│       └── web.py           # البحث والجلب
├── tests/
├── pyproject.toml
├── .env.example
└── README.md
```

---

## الاختبارات

```powershell
pip install -e ".[dev]"
pytest
```

الاختبارات لا تتصل بالشبكة؛ تستخدم مزوّداً وهمياً وأدوات محلية.

---

## استكشاف الأخطاء

**`MissingAPIKey` أو خطأ 401**
- تأكد من وجود المفتاح في `~/.mirsad/.env` أو متغيرات البيئة.
- شغّل `mirsad providers` للتأكد من الحالة.

**Ollama لا يعمل**
- تأكد أن Ollama يعمل: `ollama list`
- ثم: `mirsad chat -p ollama -m qwen2.5:7b`

**الموافقة لا تظهر / الطرفية غير تفاعلية**
- استخدم `-y` للسماح التلقائي، أو شغّل من طرفية حقيقية.

**مشاكل ترميز العربية على Windows**
- استخدم Windows Terminal، أو فعّل UTF-8:
```powershell
chcp 65001
$env:PYTHONUTF8 = "1"
```

**تعديل ملف خارج مجلد العمل**
- غير مسموح افتراضياً. انتقل للمجلد المطلوب بـ `/workdir` أو ابدأ من هناك.

---

## الترخيص

MIT
