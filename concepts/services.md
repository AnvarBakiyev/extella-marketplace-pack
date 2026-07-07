# concept: Сервисы (MCP/API) — живые данные

13 device-экспертов svc_* — обёртки публичных keyless-API. Вызываются через run_expert, возвращают JSON {status, ...}.

## svc_currency
svc_currency(base, to, amount)
Курс валют и конвертация (exchangerate-api, есть KZT). Возвращает: rate, converted, updated.

## svc_crypto
svc_crypto(coin, vs)
Курс криптовалюты (CoinGecko). coin: bitcoin/ethereum/solana; vs: usd/eur/rub.

## svc_weather
svc_weather(city)
Погода (Open-Meteo): temp_c, humidity_pct, wind_ms.

## svc_translate
svc_translate(text, src, to)
Перевод текста (MyMemory). src/to: en/ru/kk…

## svc_wiki
svc_wiki(topic)
Справка из Википедии: title, summary, url.

## svc_worldbank
svc_worldbank(country, indicator)
Экономика страны (World Bank), по умолчанию ВВП.

## svc_holidays
svc_holidays(country, year)
Госпраздники страны (Nager.Date). country: KZ/RU/US.

## svc_github
svc_github(repo)
Данные репо GitHub: stars, forks, language, desc.

## svc_hackernews
svc_hackernews(count)
Топ тех-новостей Hacker News.

## svc_books
svc_books(query)
Поиск книг (Open Library): title, author, year.

## svc_ipgeo
svc_ipgeo(ip)
Геолокация по IP: country, city, isp.

## svc_postal
svc_postal(country, code)
Место по почтовому индексу.

## svc_qr
svc_qr(data)
QR-код по ссылке/тексту → image_url.
