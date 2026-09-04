#!/bin/sh
# Проверка доступности внешних источников данных из контейнера.
#
# Запуск:
#   docker compose run --rm --no-deps api sh /app/scripts/check_network.sh
#
# Колонка http: 200/404 — хост отвечает; 000 — соединение не установлено.

check() {
    name="$1"; url="$2"
    result=$(curl -s -m 12 -o /dev/null -w "%{http_code} %{time_total}" "$url" 2>/dev/null)
    code=$(echo "$result" | cut -d' ' -f1)
    time=$(echo "$result" | cut -d' ' -f2)
    if [ "$code" = "000" ]; then
        printf "  %-34s НЕДОСТУПЕН   (%ss)\n" "$name" "$time"
    else
        printf "  %-34s http=%-5s     (%ss)\n" "$name" "$code" "$time"
    fi
}

echo "--- IP-адреса ---"
for h in api.open-meteo.com archive-api.open-meteo.com nominatim.openstreetmap.org overpass-api.de; do
    ip=$(python3 -c "import socket;print(socket.gethostbyname('$h'))" 2>/dev/null || echo '?')
    printf "  %-34s %s\n" "$h" "$ip"
done

echo "--- Доступность ---"
check "Open-Meteo (прогноз)"   "https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&past_days=10&hourly=temperature_2m"
check "Open-Meteo (архив)"     "https://archive-api.open-meteo.com/v1/archive?latitude=52.52&longitude=13.41&start_date=2023-07-01&end_date=2023-07-03&daily=temperature_2m_mean"
check "Nominatim"              "https://nominatim.openstreetmap.org/search?q=Krasnodar&format=jsonv2&limit=1"
check "Overpass"               "https://overpass-api.de/api/status"
check "Earth Engine"           "https://earthengine.googleapis.com/"
check "Google (контроль)"      "https://www.google.com/generate_204"

echo "--- Внешний IP, как его видит интернет ---"
curl -s -m 12 https://api.ipify.org 2>/dev/null && echo "" || echo "  не определён"
