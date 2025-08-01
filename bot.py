# === Приветствие ===
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент».\n\n"
    "Он поможет:\n"
    "• составить контент-план,\n"
    "• написать пост или Reels,\n"
    "• упаковать продукт.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности]"
    "(https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit) "
    "и [Договором‑офертой]"
    "(https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

INFO_QUESTIONS = [
    "✍️ Пришли свою распаковку личности и экспертности.",
    "🔥 Отлично! Теперь пришли своё позиционирование.",
    "✅ Теперь пришли характеристику продукта/услуги.",
    "📌 Пришли анализ твоей ЦА."
]

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if user_id == ADMIN_ID:
        await update.message.reply_text("👑 Привет, админ! У тебя полный доступ.")
    if args:
        if validate_token(args[0], user_id):
            await update.message.reply_text("✅ Доступ активирован! Можешь работать.")
        else:
            await update.message.reply_text("❌ Неверный или использованный токен.")
        return
    if not is_allowed(user_id):
        await update.message.reply_text("⛔️ Нет доступа. Купите доступ у администратора.")
        return
    await update.message.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]])
    )

# === Обработчик кнопок ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not is_allowed(user_id):
        await query.answer("❌ Нет доступа.", show_alert=True)
        return
    await query.answer()

    session = sessions.setdefault(user_id, {
        "state": None, "step": 0, "data": {}, "products": [],
        "audience_segments": [], "planner_data": [], "reels_data": [], "copy_data": []
    })

    # --- Согласие ---
    if query.data == "agree":
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
              [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]]
        await query.edit_message_text("Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # --- Пользователь имеет основу ---
    elif query.data == "base_yes":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    # --- Нет основы ---
    elif query.data == "base_no":
        kb = [[InlineKeyboardButton("Заполнить здесь", callback_data="fill_here")],
              [InlineKeyboardButton("Использовать другой бот", callback_data="use_other_bot")]]
        await query.edit_message_text("Давай соберём основу прямо здесь:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "fill_here":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Бот по распаковке в разработке.")

    # --- Сбор продуктов ---
    elif query.data == "add_product":
        session["state"] = "collecting_more_products"
        await query.edit_message_text("✍️ Пришли характеристику следующего продукта.")

    elif query.data == "no_more_products":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("📌 Пришли первый сегмент анализа ЦА.")

    # --- Сегменты ЦА ---
    elif query.data == "add_audience_segment":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("✍️ Пришли следующий сегмент анализа ЦА.")

    elif query.data == "audience_done":
        session["data"]["extra_info"] = "\n\n".join(session.get("audience_segments", []))
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
              [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
        await query.edit_message_text("✅ Анализ ЦА собран. Добавить дополнительную информацию?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # --- Доп. информация ---
    elif query.data == "add_extra_info":
        session["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    elif query.data == "no_extra_info":
        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Информация получена! Переходим к выбору помощников.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # === Меню помощников ===
    elif query.data == "roles_menu":
        kb = [[InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
              [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
              [InlineKeyboardButton("🎬 Reels", callback_data="role_reels")]]
        session["state"] = "menu_roles"
        await query.edit_message_text("🤖 *Твои помощники*: выбери, кто тебе нужен👇",
                                      parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# === Приветствие ===
WELCOME = (
    "👋 Привет! Ты в боте «Контент-ассистент».\n\n"
    "Он поможет:\n"
    "• составить контент-план,\n"
    "• написать пост или Reels,\n"
    "• упаковать продукт.\n\n"
    "🔐 Чтобы начать, подтверди согласие с "
    "[Политикой конфиденциальности]"
    "(https://docs.google.com/document/d/1UUyKq7aCbtrOT81VBVwgsOipjtWpro7v/edit) "
    "и [Договором‑офертой]"
    "(https://docs.google.com/document/d/1zY2hl0ykUyDYGQbSygmcgY2JaVMMZjQL/edit).\n\n"
    "✅ Нажми «СОГЛАСЕН/СОГЛАСНА» — и поехали!"
)

INFO_QUESTIONS = [
    "✍️ Пришли свою распаковку личности и экспертности.",
    "🔥 Отлично! Теперь пришли своё позиционирование.",
    "✅ Теперь пришли характеристику продукта/услуги.",
    "📌 Пришли анализ твоей ЦА."
]

# === /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if user_id == ADMIN_ID:
        await update.message.reply_text("👑 Привет, админ! У тебя полный доступ.")
    if args:
        if validate_token(args[0], user_id):
            await update.message.reply_text("✅ Доступ активирован! Можешь работать.")
        else:
            await update.message.reply_text("❌ Неверный или использованный токен.")
        return
    if not is_allowed(user_id):
        await update.message.reply_text("⛔️ Нет доступа. Купите доступ у администратора.")
        return
    await update.message.reply_text(
        WELCOME,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ СОГЛАСЕН/СОГЛАСНА", callback_data="agree")]])
    )

# === Обработчик кнопок ===
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not is_allowed(user_id):
        await query.answer("❌ Нет доступа.", show_alert=True)
        return
    await query.answer()

    session = sessions.setdefault(user_id, {
        "state": None, "step": 0, "data": {}, "products": [],
        "audience_segments": [], "planner_data": [], "reels_data": [], "copy_data": []
    })

    # --- Согласие ---
    if query.data == "agree":
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="base_yes")],
              [InlineKeyboardButton("НЕТ ❌", callback_data="base_no")]]
        await query.edit_message_text("Есть ли у тебя уже основа (распаковка, позиционирование, анализ ЦА)?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # --- Пользователь имеет основу ---
    elif query.data == "base_yes":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    # --- Нет основы ---
    elif query.data == "base_no":
        kb = [[InlineKeyboardButton("Заполнить здесь", callback_data="fill_here")],
              [InlineKeyboardButton("Использовать другой бот", callback_data="use_other_bot")]]
        await query.edit_message_text("Давай соберём основу прямо здесь:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == "fill_here":
        session.update({"state": "collecting_base_info", "step": 0})
        await query.edit_message_text(INFO_QUESTIONS[0])

    elif query.data == "use_other_bot":
        await query.edit_message_text("🤖 Бот по распаковке в разработке.")

    # --- Сбор продуктов ---
    elif query.data == "add_product":
        session["state"] = "collecting_more_products"
        await query.edit_message_text("✍️ Пришли характеристику следующего продукта.")

    elif query.data == "no_more_products":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("📌 Пришли первый сегмент анализа ЦА.")

    # --- Сегменты ЦА ---
    elif query.data == "add_audience_segment":
        session["state"] = "collecting_audience_multiple"
        await query.edit_message_text("✍️ Пришли следующий сегмент анализа ЦА.")

    elif query.data == "audience_done":
        session["data"]["extra_info"] = "\n\n".join(session.get("audience_segments", []))
        kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
              [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
        await query.edit_message_text("✅ Анализ ЦА собран. Добавить дополнительную информацию?",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # --- Доп. информация ---
    elif query.data == "add_extra_info":
        session["state"] = "waiting_extra_info"
        await query.edit_message_text("✍️ Пришли дополнительную информацию по ЦА.")

    elif query.data == "no_extra_info":
        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await query.edit_message_text("✅ Информация получена! Переходим к выбору помощников.",
                                      reply_markup=InlineKeyboardMarkup(kb))

    # === Меню помощников ===
    elif query.data == "roles_menu":
        kb = [[InlineKeyboardButton("📅 Планировщик", callback_data="role_planner")],
              [InlineKeyboardButton("✍️ Копирайтер", callback_data="role_copywriter")],
              [InlineKeyboardButton("🎬 Reels", callback_data="role_reels")]]
        session["state"] = "menu_roles"
        await query.edit_message_text("🤖 *Твои помощники*: выбери, кто тебе нужен👇",
                                      parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb))

# === Обработка сообщений ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ Нет доступа.")
        return

    session = sessions.setdefault(user_id, {"state": None, "step": 0, "data": {}, "products": []})
    text = update.message.text

    # === Сбор основной информации ===
    if session["state"] == "collecting_base_info":
        step = session["step"]
        session["data"].setdefault("info", []).append(text)
        session["step"] += 1

        if step == 2:
            kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
                  [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
            await update.message.reply_text("🔥 Отлично! Хочешь добавить ещё продукт?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            return

        if session["step"] < len(INFO_QUESTIONS):
            await update.message.reply_text(INFO_QUESTIONS[session["step"]])
        else:
            kb = [[InlineKeyboardButton("ДА ✅", callback_data="add_extra_info")],
                  [InlineKeyboardButton("НЕТ ❌", callback_data="no_extra_info")]]
            await update.message.reply_text("Хочешь отправить дополнительную информацию по ЦА?",
                                            reply_markup=InlineKeyboardMarkup(kb))
            session["state"] = "awaiting_extra"

    # === Дополнительные продукты ===
    elif session["state"] == "collecting_more_products":
        session["products"].append(text)
        kb = [[InlineKeyboardButton("Добавить ещё", callback_data="add_product")],
              [InlineKeyboardButton("Нет", callback_data="no_more_products")]]
        await update.message.reply_text("✅ Продукт добавлен. Добавить ещё?",
                                        reply_markup=InlineKeyboardMarkup(kb))

    # === Сегменты ЦА ===
    elif session["state"] == "collecting_audience_multiple":
        session["data"].setdefault("audience_segments", []).append(text)
        kb = [[InlineKeyboardButton("Добавить ещё сегмент", callback_data="add_audience_segment")],
              [InlineKeyboardButton("Закончить", callback_data="audience_done")]]
        await update.message.reply_text("✅ Сегмент добавлен. Хочешь добавить ещё?",
                                        reply_markup=InlineKeyboardMarkup(kb))

    # === Доп. информация ===
    elif session["state"] == "waiting_extra_info":
        session["data"]["extra_info"] = text
        kb = [[InlineKeyboardButton("Перейти к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Доп.информация получена. Переходим к помощникам.",
                                        reply_markup=InlineKeyboardMarkup(kb))
        session["state"] = "menu_roles"

    # === Диалог Копирайтера ===
    elif session["state"].startswith("copywriter_"):
        step = session.get("step", 0)
        session["copy_data"].append(text)
        session["step"] = step + 1

        if step == 0:
            await update.message.reply_text("2️⃣ Укажи тему текста.")
        elif step == 1:
            await update.message.reply_text("3️⃣ Укажи тональность (экспертная, дружелюбная, дерзкая).")
        elif step == 2:
            await update.message.reply_text("4️⃣ Хочешь развернутый или краткий текст?")
        elif step == 3:
            goal, topic, tone, length = session["copy_data"]
            context_text = get_user_context(session)

            # 🔥 Полный промт для OpenAI
            prompt = (
                f"Ты профессиональный копирайтер и упаковщик. Создай {session['task']} для блогера/эксперта/бренда.\n\n"
                f"=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===\n{context_text}\n\n"
                f"🎯 Цель поста: {goal}\n"
                f"📌 Тема: {topic}\n"
                f"🎨 Тональность: {tone}\n"
                f"📝 Формат текста: {length} (развернутый или краткий, но ёмкий)\n\n"

                "=== ЦЕЛИ ПОСТОВ И ЧТО УЧИТЫВАТЬ ===\n"
                "Имиджевая → истории о себе/бренде, ценности, миссия, кейсы\n"
                "Вовлекающая → опросы, челленджи, вопросы, дискуссии\n"
                "Образовательная → инструкции, гайды, разборы, чек-листы, экспертные советы\n"
                "Продающая → офферы, акции, отзывы, демонстрация продукта\n"
                "Прогревающая → истории клиентов, закулисье продукта, полезные факты\n"
                "Вирусная → тренды, мемы, провокационные темы, эмоциональные видео\n"
                "Информационная → анонсы, новости, релизы, события\n"
                "Развлекательная → юмор, подборки, легкие факты, блиц-опросы\n\n"

                "=== ЕСЛИ ФОРМАТ = ПОСТ-КАРУСЕЛЬ ===\n"
                "✅ Используй структуру 10 слайдов:\n"
                "1. Крючок – захват внимания (1-2 секунды)\n"
                "2. Проблема – боль ЦА\n"
                "3. Усиление боли – последствия, упущенные выгоды\n"
                "4. Обещание решения – надежда на результат\n"
                "5–8. Контент – пошаговая инструкция, советы, факты, чек-лист\n"
                "9. Призыв к действию (CTA) – «Сохрани», «Напиши +», «Поделись»\n"
                "10. Оффер/экспертность – автор, упоминание услуги, мягкий оффер\n\n"

                "=== ОБЯЗАТЕЛЬНАЯ СТРУКТУРА ЛЮБОГО ТЕКСТА ===\n"
                "– Заголовок (цепляет, максимум 5–7 слов)\n"
                "– Вступление (подводит, цепляет эмоцией)\n"
                "– Основная часть (логично, структурно, без воды)\n"
                "– Вывод или CTA (побуждение к действию)\n"
                "– Оффер или УТП (если уместно)\n\n"

                "=== СТИЛЬ ПИСЬМА ===\n"
                "– Пиши цепко, по-человечески, без клише\n"
                "– Используй стиль 2024–2025: коротко, просто, с эмоцией\n"
                "– Применяй сторителлинг, честный контент, вовлечение\n"
                "– Упрощай и усиливай, если текст есть\n\n"

                "⚖️ Соблюдай Федеральный закон №38-ФЗ и №72-ФЗ от 07.04.2025: "
                "не используй фразы «100% результат», «лучший», «гарантировано», "
                "заменяй их корректными альтернативами: «один из популярных вариантов», «подходит для…», «узнай подробнее».\n\n"

                "💡 Выдай текст в структурированном виде, готовый к публикации."
            )

            await update.message.reply_text("✍️ Пишу текст, подожди...")
            try:
                response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                        messages=[{"role": "user", "content": prompt}])
                result = sanitize_ad_text(response["choices"][0]["message"]["content"])
                await send_long_message(update.effective_chat.id, result, context)
            except Exception as e:
                await update.message.reply_text("⚠️ Ошибка генерации текста.")
                print("OpenAI Error:", e)

            session["state"] = "menu_roles"
            kb = [[InlineKeyboardButton("Вернуться к помощникам", callback_data="roles_menu")]]
            await update.message.reply_text("✅ Готово!", reply_markup=InlineKeyboardMarkup(kb))

    # === Планировщик ===
    elif session["state"] == "planner_goal":
        session["planner_data"] = [text]
        session["state"] = "planner_platform"
        await update.message.reply_text("2️⃣ Укажи основную соцсеть.")

    elif session["state"] == "planner_platform":
        session["planner_data"].append(text)
        session["state"] = "planner_frequency"
        await update.message.reply_text("3️⃣ Укажи частоту публикаций.")

    elif session["state"] == "planner_frequency":
        session["planner_data"].append(text)
        session["state"] = "planner_face"
        await update.message.reply_text("4️⃣ От чьего лица вести контент?")

    elif session["state"] == "planner_face":
        session["planner_data"].append(text)
        session["state"] = "planner_days"
        await update.message.reply_text("5️⃣ На какой срок нужен план?")

    elif session["state"] == "planner_days":
        session["planner_data"].append(text)
        goal, platform, freq, face, days = session["planner_data"]
        context_text = get_user_context(session)

        # 🔥 Полный промт для планировщика
        prompt = (
            f"Ты контент-планировщик. Твоя задача – создать развернутый, детализированный контент-план.\n\n"
            f"=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===\n{context_text}\n\n"
            f"🎯 Цель: {goal}\n"
            f"📌 Платформа: {platform}\n"
            f"📅 Срок: {days} дней\n"
            f"🗓 Частота публикаций: {freq}\n"
            f"👤 От чьего лица вести: {face}\n\n"

            "=== АНАЛИЗ ЦЕЛЕВОЙ АУДИТОРИИ ===\n"
            "Пользователь прислал несколько сегментов ЦА. "
            "Для каждого дня указывай, для какого сегмента подходит контент (или для нескольких). "
            "Обязательно используй данные сегментов, а не пиши общие советы.\n\n"

            "=== ТРЕБОВАНИЯ К ПЛАНУ ===\n"
            "– Каждый день должен включать: сторис + (или рилс / пост-карусель)\n"
            "– Укажи для каждого дня: тему, формат, цель, CTA, идеи сторис, визуальные подсказки\n"
            "– Раздели контент по рубрикатору: экспертность, вовлечение, личное, кейсы, продажи\n"
            "– Привяжи каждый день к этапу воронки: холодная, тёплая, горячая аудитория\n"
            "– Добавляй пометку [Сегмент ЦА: ...] для каждого элемента контента\n\n"

            "=== ФОРМАТ ВЫВОДА ===\n"
            "День 1:\n• Сторис – тема, идея, CTA [Сегмент ЦА: сегмент1]\n• Рилс/Пост – тема, формат, краткий сценарий, CTA [Сегмент ЦА: сегмент2]\n\n"
            "День 2:\n• … (и так далее для всех дней)\n\n"

            "=== СПЕЦИФИКА ===\n"
            "– План должен быть практичным, а не общими советами\n"
            "– Учитывай возможности автора (если публикаций мало – оптимизируй)\n"
            "– Используй форматы 2024–2025: Reels, сторис, карусели, behind-the-scenes\n"
            "– Добавляй конкретные идеи для визуала, интерактивов, опросов\n\n"

            "⚖️ Соблюдай закон №38-ФЗ и №72-ФЗ от 07.04.2025, исключи запрещённые обещания, используй корректные формулировки.\n"
            "Выдай план в структурированном виде, по дням, без сокращений «и так далее»."
        )

        await update.message.reply_text("📅 Формирую контент-план, подожди...")
        try:
            response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                    messages=[{"role": "user", "content": prompt}])
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.effective_chat.id, result, context)
        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка генерации плана.")
            print("Planner Error:", e)

        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Вернуться к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text("✅ План готов!", reply_markup=InlineKeyboardMarkup(kb))

    # === Reels ===
    elif session["state"] == "reels_topic":
        session["reels_data"] = [text]
        session["state"] = "reels_format"
        await update.message.reply_text("2️⃣ Укажи формат: с лицом / без лица / монтаж.")

    elif session["state"] == "reels_format":
        session["reels_data"].append(text)
        session["state"] = "reels_style"
        await update.message.reply_text("3️⃣ Укажи стиль: экспертный / юмор / душевный.")

    elif session["state"] == "reels_style":
        session["reels_data"].append(text)
        session["state"] = "reels_music"
        await update.message.reply_text("4️⃣ Есть ли музыка или референс?")

    elif session["state"] == "reels_music":
        session["reels_data"].append(text)
        topic, format_r, style, music = session["reels_data"]
        context_text = get_user_context(session)

        # 🔥 Полный промт для Reels
        prompt = (
            f"Ты профессиональный продюсер коротких видео (Reels, TikTok, Shorts, ВК-клипы). "
            f"Создай сценарий для видео по данным пользователя.\n\n"
            f"=== ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ===\n{context_text}\n\n"
            f"🎯 Тема ролика: {topic}\n"
            f"📹 Формат: {format_r} (с лицом / без лица / монтаж)\n"
            f"🎨 Стиль: {style}\n"
            f"🎵 Музыка/референс: {music}\n\n"

            "=== ОБЯЗАТЕЛЬНАЯ СТРУКТУРА СЦЕНАРИЯ ===\n"
            "1️⃣ Хук (2–3 секунды, мощный захват внимания)\n"
            "2️⃣ Основной блок (пошаговый сценарий: текст, действия, визуал)\n"
            "3️⃣ CTA (призыв к действию: сохранить, подписаться, написать)\n"
            "4️⃣ Альтернативы: вариант для видео с лицом и без\n"
            "5️⃣ Подсказки по визуалу, монтажу, свету (конкретные советы)\n\n"

            "=== ТРЕБОВАНИЯ ===\n"
            "– Используй сторителлинг, эмоции, провокационные или цепляющие элементы\n"
            "– Применяй тренды 2024–2025 (быстрый хук, честная подача)\n"
            "– Встраивай честный оффер, если это уместно\n"
            "– Делай сценарий максимально практичным и готовым к съёмке\n\n"

            "⚖️ Соблюдай Федеральный закон №38-ФЗ «О рекламе» и №72-ФЗ от 07.04.2025: "
            "не используй необоснованные обещания («100% результат», «лучший», «гарантировано»), "
            "заменяй их корректными альтернативами («один из популярных вариантов», «подходит для…», «узнай подробнее»)."
        )

        await update.message.reply_text("🎬 Генерирую сценарий, подожди...")
        try:
            response = openai.ChatCompletion.create(model="gpt-3.5-turbo",
                                                    messages=[{"role": "user", "content": prompt}])
            result = sanitize_ad_text(response["choices"][0]["message"]["content"])
            await send_long_message(update.effective_chat.id, result, context)
        except Exception as e:
            await update.message.reply_text("⚠️ Ошибка генерации сценария.")
            print("Reels Error:", e)

        session["state"] = "menu_roles"
        kb = [[InlineKeyboardButton("Вернуться к помощникам", callback_data="roles_menu")]]
        await update.message.reply_text("✅ Сценарий готов!", reply_markup=InlineKeyboardMarkup(kb))

# === Хендлер неизвестных сообщений ===
async def any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_allowed(user_id):
        await update.message.reply_text("❌ Нет доступа.")
        return
    await update.message.reply_text("🤔 Я не понял команду. Нажми /start, чтобы начать заново.")

# === Запуск бота (твой рабочий вариант) ===
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("gentoken", gentoken))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.ALL, any_message))

    print("🚀 Бот запущен! Ждём пользователей...")
    app.run_polling()
