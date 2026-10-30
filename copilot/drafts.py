"""Шаблонные черновики ответов на языке игрока.

Шаблоны ничего не обещают (ни наказания, ни разбана, ни возврата) и ссылаются только на
пункты, которые реально есть в rules.json. LLM-слой (llm.py) может переписать черновик
естественнее, но цитаты всё равно проходят через rules.validate_citations.
"""

GREET = {
    "ru": "Здравствуйте{name}!",
    "kk": "Сәлеметсіз бе{name}!",
    "uz": "Assalomu alaykum{name}!",
    "en": "Hello{name}!",
    "es": "¡Hola{name}!",
    "pt": "Olá{name}!",
}
SIGN = {
    "ru": "С уважением, администрация Grand Mobile.",
    "kk": "Құрметпен, Grand Mobile әкімшілігі.",
    "uz": "Hurmat bilan, Grand Mobile ma'muriyati.",
    "en": "Best regards, Grand Mobile administration.",
    "es": "Atentamente, la administración de Grand Mobile.",
    "pt": "Atenciosamente, administração do Grand Mobile.",
}

# {rules} — список пунктов («ОП 2.1, GZ 1.1»), {nick} — ник обвиняемого
BODY = {
    "offtopic": {
        "ru": "Пожалуйста, опишите ваш вопрос или проблему подробнее, чтобы мы могли помочь. Репорт предназначен для вопросов и помощи по игре, оффтоп и флуд в репорт запрещены ({rules}).",
        "kk": "Көмектесуіміз үшін сұрағыңызды немесе мәселеңізді толығырақ жазыңыз. Репорт ойын бойынша сұрақтар мен көмекке арналған, оффтоп пен флудқа тыйым салынған ({rules}).",
        "uz": "Yordam bera olishimiz uchun savolingiz yoki muammoingizni batafsilroq yozing. Report o'yin bo'yicha savollar va yordam uchun mo'ljallangan, offtop va flud taqiqlangan ({rules}).",
        "en": "Please describe your question or problem in more detail so we can help. Reports are for game questions and help; off-topic messages and flooding are not allowed ({rules}).",
        "es": "Por favor, describe tu pregunta o problema con más detalle para que podamos ayudarte. El reporte es para preguntas y ayuda sobre el juego; el offtopic y el flood están prohibidos ({rules}).",
        "pt": "Por favor, descreva sua pergunta ou problema com mais detalhes para que possamos ajudar. O report é para dúvidas e ajuda sobre o jogo; offtopic e flood são proibidos ({rules}).",
    },
    "help": {
        "ru": "Ваш запрос получен, администратор подключится и постарается помочь. Если ситуация изменилась, напишите, где именно вы находитесь и что произошло.",
        "kk": "Сұранысыңыз қабылданды, әкімші қосылып, көмектесуге тырысады. Жағдай өзгерсе, қай жерде екеніңізді және не болғанын жазыңыз.",
        "uz": "So'rovingiz qabul qilindi, administrator ulanib, yordam berishga harakat qiladi. Vaziyat o'zgarsa, aynan qayerdaligingiz va nima bo'lganini yozing.",
        "en": "Your request has been received; an administrator will join and try to help. If anything changes, please write where exactly you are and what happened.",
        "es": "Hemos recibido tu solicitud; un administrador se conectará e intentará ayudarte. Si algo cambia, escribe dónde estás exactamente y qué pasó.",
        "pt": "Recebemos sua solicitação; um administrador vai se conectar e tentar ajudar. Se algo mudar, escreva onde exatamente você está e o que aconteceu.",
    },
    "question": {
        "ru": "Спасибо за вопрос. Уточните, пожалуйста, детали (сервер, что именно вы пытаетесь сделать), и администратор подскажет. Для общих вопросов также можно использовать Discord-сервер игры.",
        "kk": "Сұрағыңызға рахмет. Толығырақ жазыңызшы (сервер, нақты не істегіңіз келеді), әкімші түсіндіреді. Жалпы сұрақтар үшін ойынның Discord-серверін де қолдануға болады.",
        "uz": "Savolingiz uchun rahmat. Iltimos, tafsilotlarni yozing (server, aynan nima qilmoqchisiz), administrator tushuntirib beradi. Umumiy savollar uchun o'yinning Discord-serveridan ham foydalanishingiz mumkin.",
        "en": "Thank you for your question. Please add details (server, what exactly you are trying to do) and an administrator will help. For general questions you can also use the game's Discord server.",
        "es": "Gracias por tu pregunta. Por favor, añade detalles (servidor, qué intentas hacer exactamente) y un administrador te ayudará. Para preguntas generales también puedes usar el servidor de Discord del juego.",
        "pt": "Obrigado pela pergunta. Por favor, adicione detalhes (servidor, o que exatamente você está tentando fazer) e um administrador vai ajudar. Para dúvidas gerais, você também pode usar o servidor do Discord do jogo.",
    },
    # Ответ из базы прошлых ответов администраторов (база на русском, поэтому только для ru без LLM)
    "question_kb": {
        "ru": "Похожий вопрос уже задавали, ответ администрации: «{answer}». Если ваш вопрос о другом, уточните его, пожалуйста.",
    },
    "report_complaint": {
        "ru": "Если игрок нарушает правила, подайте жалобу через лаунчер. В жалобе нужны точное описание ситуации и полные доказательства: видео или скриншоты ({rules}). Без доказательств администрация не может наказать игрока.",
        "kk": "Егер ойыншы ережені бұзса, лаунчер арқылы шағым жіберіңіз. Шағымда жағдайдың нақты сипаттамасы мен толық дәлелдер болуы керек: видео немесе скриншоттар ({rules}). Дәлелсіз әкімшілік ойыншыны жазалай алмайды.",
        "uz": "Agar o'yinchi qoidalarni buzayotgan bo'lsa, launcher orqali shikoyat yuboring. Shikoyatda vaziyatning aniq tavsifi va to'liq dalillar bo'lishi kerak: video yoki skrinshotlar ({rules}). Dalilsiz ma'muriyat o'yinchini jazolay olmaydi.",
        "en": "If a player is breaking the rules, please file a complaint through the launcher. It must include an exact description and full evidence: video or screenshots ({rules}). Without evidence the administration cannot punish the player.",
        "es": "Si un jugador incumple las reglas, presenta una queja a través del launcher. Debe incluir una descripción exacta y pruebas completas: video o capturas ({rules}). Sin pruebas la administración no puede sancionar al jugador.",
        "pt": "Se um jogador estiver quebrando as regras, envie uma denúncia pelo launcher. Ela deve conter uma descrição exata e provas completas: vídeo ou capturas de tela ({rules}). Sem provas a administração não pode punir o jogador.",
    },
    "account": {
        "ru": "Ваше обращение передано администрации. Никому не сообщайте пароль и коды подтверждения. Обратите внимание: игрок сам отвечает за сохранность аккаунта и имущества ({rules}), поэтому решение по вашей ситуации примет администратор после проверки.",
        "kk": "Өтінішіңіз әкімшілікке жіберілді. Құпиясөзді және растау кодтарын ешкімге айтпаңыз. Назар аударыңыз: аккаунт пен мүліктің қауіпсіздігіне ойыншының өзі жауап береді ({rules}), сондықтан шешімді әкімші тексеруден кейін қабылдайды.",
        "uz": "Murojaatingiz ma'muriyatga yuborildi. Parol va tasdiqlash kodlarini hech kimga bermang. E'tibor bering: akkaunt va mol-mulk xavfsizligi uchun o'yinchining o'zi javobgar ({rules}), shuning uchun qarorni administrator tekshiruvdan so'ng qabul qiladi.",
        "en": "Your request has been forwarded to the administration. Never share your password or confirmation codes. Please note that players are responsible for the security of their account and property ({rules}), so an administrator will decide after reviewing your case.",
        "es": "Tu solicitud se ha enviado a la administración. No compartas tu contraseña ni códigos de confirmación. Ten en cuenta que cada jugador es responsable de la seguridad de su cuenta y bienes ({rules}); un administrador decidirá tras revisar tu caso.",
        "pt": "Sua solicitação foi encaminhada à administração. Nunca compartilhe sua senha ou códigos de confirmação. Observe que o jogador é responsável pela segurança da conta e dos bens ({rules}); um administrador decidirá após analisar o caso.",
    },
    "payment": {
        "ru": "Ваше обращение по платежу передано ответственному сотруднику. Чтобы ускорить проверку, укажите дату и время оплаты, сумму, способ оплаты и ник персонажа. Если есть чек, приложите его.",
        "kk": "Төлем бойынша өтінішіңіз жауапты қызметкерге жіберілді. Тексеруді жылдамдату үшін төлем күні мен уақытын, сомасын, төлем тәсілін және кейіпкер никін көрсетіңіз. Чек болса, қоса жіберіңіз.",
        "uz": "To'lov bo'yicha murojaatingiz mas'ul xodimga yuborildi. Tekshiruvni tezlashtirish uchun to'lov sanasi va vaqtini, summasini, to'lov usulini va personaj nikini yozing. Chek bo'lsa, ilova qiling.",
        "en": "Your payment request has been forwarded to the responsible team member. To speed up the check, please provide the date and time of payment, amount, payment method and your character's nickname. Attach the receipt if you have one.",
        "es": "Tu solicitud sobre el pago se ha enviado al responsable. Para agilizar la revisión, indica fecha y hora del pago, importe, método de pago y el nick del personaje. Adjunta el recibo si lo tienes.",
        "pt": "Sua solicitação sobre pagamento foi encaminhada ao responsável. Para agilizar, informe data e hora do pagamento, valor, método de pagamento e o nick do personagem. Anexe o comprovante, se tiver.",
    },
    "complaint_review": {
        "ru": "Ваша жалоба{on_nick} принята к рассмотрению. Предполагаемое нарушение: {rules}. Администратор проверит доказательства и вынесет решение; жалобы рассматриваются в течение 48 часов.",
        "kk": "Шағымыңыз{on_nick} қарауға қабылданды. Болжамды бұзушылық: {rules}. Әкімші дәлелдерді тексеріп, шешім шығарады; шағымдар 48 сағат ішінде қаралады.",
        "uz": "Shikoyatingiz{on_nick} ko'rib chiqish uchun qabul qilindi. Taxminiy qoidabuzarlik: {rules}. Administrator dalillarni tekshirib, qaror chiqaradi; shikoyatlar 48 soat ichida ko'rib chiqiladi.",
        "en": "Your complaint{on_nick} has been accepted for review. Possible violation: {rules}. An administrator will check the evidence and make a decision; complaints are reviewed within 48 hours.",
        "es": "Tu queja{on_nick} ha sido aceptada para revisión. Posible infracción: {rules}. Un administrador revisará las pruebas y tomará una decisión; las quejas se revisan en 48 horas.",
        "pt": "Sua denúncia{on_nick} foi aceita para análise. Possível infração: {rules}. Um administrador vai verificar as provas e tomar uma decisão; denúncias são analisadas em até 48 horas.",
    },
    "complaint_no_evidence": {
        "ru": "Предоставленных материалов недостаточно для рассмотрения жалобы. Приложите полные, необрезанные видео или скриншоты, на которых однозначно видно нарушение, и опишите, что произошло ({rules}).",
        "kk": "Шағымды қарау үшін ұсынылған материалдар жеткіліксіз. Бұзушылық анық көрінетін толық, кесілмеген видео немесе скриншоттарды қосып, не болғанын сипаттаңыз ({rules}).",
        "uz": "Shikoyatni ko'rib chiqish uchun taqdim etilgan materiallar yetarli emas. Qoidabuzarlik aniq ko'rinadigan to'liq, kesilmagan video yoki skrinshotlarni ilova qiling va nima bo'lganini yozing ({rules}).",
        "en": "The materials provided are not sufficient to review the complaint. Please attach full, uncut videos or screenshots that clearly show the violation and describe what happened ({rules}).",
        "es": "Los materiales aportados no son suficientes para revisar la queja. Adjunta videos o capturas completos, sin recortes, donde se vea claramente la infracción, y describe lo ocurrido ({rules}).",
        "pt": "Os materiais enviados não são suficientes para analisar a denúncia. Anexe vídeos ou capturas completos, sem cortes, que mostrem claramente a infração, e descreva o que aconteceu ({rules}).",
    },
    "complaint_rejected": {
        "ru": "По результатам проверки нарушений правил не выявлено. Если у вас есть дополнительные доказательства, подайте новую жалобу с полным описанием ситуации ({rules}).",
        "kk": "Тексеру нәтижесінде ереже бұзушылық анықталмады. Қосымша дәлелдеріңіз болса, жағдайды толық сипаттап, жаңа шағым жіберіңіз ({rules}).",
        "uz": "Tekshiruv natijasida qoidabuzarlik aniqlanmadi. Qo'shimcha dalillaringiz bo'lsa, vaziyatni to'liq tavsiflab, yangi shikoyat yuboring ({rules}).",
        "en": "After review, no rule violation was found. If you have additional evidence, please file a new complaint with a full description of the situation ({rules}).",
        "es": "Tras la revisión, no se encontró ninguna infracción de las reglas. Si tienes pruebas adicionales, presenta una nueva queja con una descripción completa de la situación ({rules}).",
        "pt": "Após a análise, não foi encontrada nenhuma infração às regras. Se você tiver provas adicionais, envie uma nova denúncia com uma descrição completa da situação ({rules}).",
    },
    "already_punished": {
        "ru": "Спасибо за обращение. Этот игрок уже был наказан за данное нарушение, повторное наказание за тот же случай не выдаётся.",
        "kk": "Өтінішіңізге рахмет. Бұл ойыншы осы бұзушылық үшін жазасын алған, бір жағдай үшін қайта жаза берілмейді.",
        "uz": "Murojaatingiz uchun rahmat. Bu o'yinchi ushbu qoidabuzarlik uchun allaqachon jazolangan, bir holat uchun qayta jazo berilmaydi.",
        "en": "Thank you for your report. This player has already been punished for this violation; the same case is not punished twice.",
        "es": "Gracias por tu reporte. Este jugador ya fue sancionado por esta infracción; el mismo caso no se sanciona dos veces.",
        "pt": "Obrigado pela denúncia. Este jogador já foi punido por esta infração; o mesmo caso não é punido duas vezes.",
    },
    "appeal_rejected": {
        "ru": "Мы проверили ваше обращение: наказание выдано в соответствии с правилами и остаётся в силе. Жалобы на действия администраторов рассматриваются только через соответствующий раздел ({rules}).",
        "kk": "Өтінішіңізді тексердік: жаза ережеге сай берілген және күшінде қалады. Әкімшілер әрекетіне шағымдар тек тиісті бөлім арқылы қаралады ({rules}).",
        "uz": "Murojaatingizni tekshirdik: jazo qoidalarga muvofiq berilgan va kuchda qoladi. Administratorlar ustidan shikoyatlar faqat tegishli bo'lim orqali ko'rib chiqiladi ({rules}).",
        "en": "We have reviewed your request: the punishment was issued in accordance with the rules and remains in force. Complaints about administrators are reviewed only through the dedicated section ({rules}).",
        "es": "Hemos revisado tu solicitud: la sanción se aplicó conforme a las reglas y se mantiene. Las quejas sobre administradores solo se revisan a través de la sección correspondiente ({rules}).",
        "pt": "Analisamos sua solicitação: a punição foi aplicada de acordo com as regras e continua em vigor. Denúncias contra administradores são analisadas apenas pela seção correspondente ({rules}).",
    },
    "complaint_invalid": {
        "ru": "Жалоба оформлена не по правилам: в ней должно быть точное и понятное описание произошедшего и доказательства ({rules}). Раздел жалоб не предназначен для вопросов и обсуждений, для них используйте репорт или Discord-сервер игры.",
        "kk": "Шағым ережеге сай рәсімделмеген: онда болған жағдайдың нақты әрі түсінікті сипаттамасы мен дәлелдер болуы керек ({rules}). Шағым бөлімі сұрақтар мен талқылауға арналмаған, олар үшін репортты немесе ойынның Discord-серверін қолданыңыз.",
        "uz": "Shikoyat qoidalarga muvofiq rasmiylashtirilmagan: unda voqeaning aniq va tushunarli tavsifi hamda dalillar bo'lishi kerak ({rules}). Shikoyatlar bo'limi savollar va muhokamalar uchun emas, ular uchun report yoki o'yinning Discord-serveridan foydalaning.",
        "en": "The complaint is not filed according to the rules: it must contain an exact, clear description of what happened and evidence ({rules}). The complaints section is not for questions or discussions; please use reports or the game's Discord server.",
        "es": "La queja no cumple las reglas: debe incluir una descripción exacta y clara de lo ocurrido y pruebas ({rules}). La sección de quejas no es para preguntas ni discusiones; usa el reporte o el servidor de Discord del juego.",
        "pt": "A denúncia não segue as regras: deve conter uma descrição exata e clara do ocorrido e provas ({rules}). A seção de denúncias não é para perguntas ou discussões; use o report ou o servidor do Discord do jogo.",
    },
    "duplicate": {
        "ru": "Эта жалоба повторяет уже поданную или рассмотренную ({rules}). Пожалуйста, дождитесь ответа по первой жалобе и не отправляйте её повторно.",
        "kk": "Бұл шағым бұрын жіберілген немесе қаралған шағымды қайталайды ({rules}). Бірінші шағым бойынша жауапты күтіңіз және оны қайта жібермеңіз.",
        "uz": "Bu shikoyat avval yuborilgan yoki ko'rib chiqilgan shikoyatni takrorlaydi ({rules}). Iltimos, birinchi shikoyat bo'yicha javobni kuting va uni qayta yubormang.",
        "en": "This complaint duplicates one that was already filed or reviewed ({rules}). Please wait for the answer to the first complaint and do not send it again.",
        "es": "Esta queja duplica una ya enviada o revisada ({rules}). Espera la respuesta a la primera queja y no la envíes de nuevo.",
        "pt": "Esta denúncia repete uma já enviada ou analisada ({rules}). Aguarde a resposta da primeira denúncia e não a envie novamente.",
    },
    "appeal": {
        "ru": "Ваше обращение по наказанию передано старшей администрации. Решение о наказании пересматривает администрация после проверки. Приложите скриншот выданного наказания и опишите ситуацию; жалобы на действия администраторов подаются в течение 2 дней ({rules}).",
        "kk": "Жаза бойынша өтінішіңіз аға әкімшілікке жіберілді. Жаза туралы шешімді әкімшілік тексеруден кейін қайта қарайды. Берілген жазаның скриншотын қосып, жағдайды сипаттаңыз; әкімшілер әрекетіне шағым 2 күн ішінде беріледі ({rules}).",
        "uz": "Jazo bo'yicha murojaatingiz katta ma'muriyatga yuborildi. Jazo bo'yicha qarorni ma'muriyat tekshiruvdan so'ng qayta ko'rib chiqadi. Berilgan jazo skrinshotini ilova qiling va vaziyatni yozing; administratorlar ustidan shikoyat 2 kun ichida beriladi ({rules}).",
        "en": "Your request about the punishment has been forwarded to senior administration. The decision is reviewed by the administration after checking. Please attach a screenshot of the punishment and describe the situation; complaints about administrators are filed within 2 days ({rules}).",
        "es": "Tu solicitud sobre la sanción se ha enviado a la administración superior. La decisión se revisará tras la comprobación. Adjunta una captura de la sanción y describe la situación; las quejas sobre administradores se presentan en un plazo de 2 días ({rules}).",
        "pt": "Sua solicitação sobre a punição foi encaminhada à administração superior. A decisão será revisada após verificação. Anexe uma captura da punição e descreva a situação; denúncias contra administradores são feitas em até 2 dias ({rules}).",
    },
}

ON_NICK = {
    "ru": " на игрока {nick}", "kk": " ({nick} ойыншысына)", "uz": " ({nick} o'yinchisiga)",
    "en": " against {nick}", "es": " contra {nick}", "pt": " contra {nick}",
}


def render(situation: str, lang: str, rule_codes: list[str], nick: str | None = None,
           player_name: str | None = None, answer: str = "") -> str:
    lang = lang if lang in BODY[situation] else "ru"
    body = BODY[situation][lang]
    on_nick = ON_NICK[lang].format(nick=nick) if nick else ""
    text = body.format(rules=", ".join(rule_codes) or "—", on_nick=on_nick, answer=answer.rstrip(". "))
    if "({rules})" in BODY[situation][lang] and not rule_codes:
        text = text.replace(" (—)", "")
    greet = GREET[lang].format(name=f", {player_name}" if player_name else "")
    return f"{greet} {text}\n\n{SIGN[lang]}"
