"""Можно ли верить найденному событию.

Это отдельный вопрос от «насколько плохо». Риск отвечает на второй,
доверие — на первый, и смешивать их нельзя: получилось бы число, по которому
не понять ни того, ни другого.

Модуль заменяет три прежних показателя одним. Так вышло не из любви к порядку,
а потому что все три меряли не то, что обещали.

`confidence` аномалии складывался из числа точек, длительности и доли
восстановленных значений. Но «точки» — это дни суточной сетки, то есть та же
длительность, а доля восстановленных значений равна примерно 0,8 у любого
события: восстановление заполняет каждый день периода, а Sentinel-2 летает
раз в пять суток. Замер по базе: 0,75–1,00 без единого исключения. То есть
показатель был длительностью, переодетой в уверенность.

`corroboration` считал сумму баллов и на том же месте спотыкался. Один
физический факт — облачное окно — списывался трижды: понижением веса оптики,
потерей балла за устойчивость и отдельным штрафом за облачность. В итоге
событие, на котором сошлись радар и погода, получало вердикт «слабое».

Понижение уверенности вдвое при несовпадении фазы сезона было третьим
показателем и вовсе не показывалось: пользователь видел упавшее число,
но не знал почему.

Отсюда правила, на которых построена замена.

**Отсутствие свидетельства — не свидетельство против.** Радара в окне нет —
мы не знаем, а не «событие сомнительное». Понижать по этому доверие нельзя
особенно: радарных данных не хватает независимо от состояния поля.

**Один факт списывается один раз.** Облачность — это и есть мера слабости
оптики, а не добавка к ней.

**Слабая оптика не отменяет сильный радар.** Ровно наоборот: радар и добавлялся
ради окон, где оптика рвётся. Логика, топившая подтверждённое радаром событие
облачным штрафом, отменяла смысл собственного источника.

**Молчание радара опровергает только слабую оптику.** Радар видит структуру
полога, оптика — спектральное состояние листа. Хлороз или азотное голодание
меняют цвет, не меняя структуру, поэтому у надёжно измеренного оптического
события молчащий радар означает «проблема спектральная», а не «события не было».

Числа на выходе нет намеренно. Веса прежней суммы были назначены, а не
откалиброваны, и «35 из 100» выглядело измерением, будучи мнением. Три
состояния опираются на факты и потому защитимы.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date

from agropulse.analytics.radar import (
    RADAR_AGREES,
    RADAR_NO_DATA,
    RADAR_SILENT,
)

# --- сила оптического свидетельства ---------------------------------------

OPTICAL_STRONG = "strong"   # событие измерено, а не выведено
OPTICAL_WEAK = "weak"       # измерение одно или сильно замутнено
OPTICAL_NONE = "none"       # в окне нет ни одного настоящего снимка

# Сколько настоящих наблюдений в окне делают оптику самостоятельным
# свидетельством. Два — минимум, при котором событие не опирается на
# единственную точку, которая могла быть недомаскированным облаком.
MIN_OBSERVATIONS_FOR_STRONG = 2

# Доля пригодных пикселей, ниже которой снимок считается замутнённым.
MIN_COVERAGE_FOR_STRONG = 0.5

# --- итоговый вердикт ------------------------------------------------------

TRUST_CONFIRMED = "confirmed"     # событию можно верить
TRUST_UNVERIFIED = "unverified"   # проверить было нечем
TRUST_DISPUTED = "disputed"       # независимый источник возражает


@dataclass(slots=True)
class Trust:
    """Вердикт о доверии к событию вместе с его основаниями."""

    level: str
    optical: str
    radar: str
    # Погода объясняет механизм, но не подтверждает измерение, поэтому
    # на вердикт не влияет и живёт отдельным признаком.
    weather_explains: bool = False
    # Сезон не совпал по форме с историей поля — сравнивать было не с чем.
    phase_mismatch: bool = False
    observations: int = 0
    coverage: float | None = None
    reasons: list[str] = dataclass_field(default_factory=list)


def optical_strength(observations: int, coverage: float | None) -> str:
    """Насколько оптика сама по себе является свидетельством.

    Считаются настоящие наблюдения в окне события, а не точки суточной сетки:
    восстановленные значения — это следствие вывода, а не его основание,
    и подтверждать событие сами собой они не могут.
    """
    if observations <= 0:
        return OPTICAL_NONE
    if observations < MIN_OBSERVATIONS_FOR_STRONG:
        return OPTICAL_WEAK
    if coverage is not None and coverage < MIN_COVERAGE_FOR_STRONG:
        return OPTICAL_WEAK
    return OPTICAL_STRONG


def assess(
    *,
    observations: int,
    coverage: float | None,
    radar: str,
    weather_explains: bool,
    phase_mismatch: bool,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Trust:
    """Свести свидетельства в один вердикт.

    Таблица решений — оптика против радара, три на три. Она короткая
    намеренно: правило, которое нельзя пересказать вслух за десять секунд,
    невозможно и защитить перед пользователем.
    """
    optical = optical_strength(observations, coverage)
    reasons: list[str] = []

    # Несовпадение фазы сезона бьёт по самому основанию сравнения: норма
    # построена по годам, когда на поле могла расти другая культура. Такое
    # событие не подтверждается ничем, пока культура не уточнена.
    if phase_mismatch:
        reasons.append(
            "динамика сезона не совпала с историей поля — вероятна смена культуры "
            "или другие сроки сева, и сравнивать было не с чем"
        )
        return Trust(
            level=TRUST_UNVERIFIED,
            optical=optical,
            radar=radar,
            weather_explains=weather_explains,
            phase_mismatch=True,
            observations=observations,
            coverage=coverage,
            reasons=reasons,
        )

    reasons.append(_optical_reason(optical, observations, coverage))
    reasons.append(_radar_reason(radar))
    if weather_explains:
        reasons.append("погода объясняет механизм ухудшения")

    if radar == RADAR_AGREES:
        # Независимая физика согласна. Это сильнейшее свидетельство, какое
        # у сервиса есть, и слабость оптики его не отменяет — ради таких
        # окон радар и подключался.
        level = TRUST_CONFIRMED
    elif optical == OPTICAL_STRONG:
        # Оптика измерила событие сама. Молчащий радар этого не опровергает:
        # он не видит того, что меняет цвет, но не структуру.
        level = TRUST_CONFIRMED
        if radar == RADAR_SILENT:
            reasons.append(
                "радар структурных изменений не показывает — ухудшение может быть "
                "спектральным, без потери массы"
            )
    elif radar == RADAR_SILENT:
        # Оптика слаба, и единственный независимый источник, у которого есть
        # данные, события не подтверждает.
        level = TRUST_DISPUTED
    else:
        level = TRUST_UNVERIFIED

    return Trust(
        level=level,
        optical=optical,
        radar=radar,
        weather_explains=weather_explains,
        phase_mismatch=False,
        observations=observations,
        coverage=coverage,
        reasons=reasons,
    )


def _optical_reason(optical: str, observations: int, coverage: float | None) -> str:
    if optical == OPTICAL_NONE:
        return "в окне события нет ни одного пригодного снимка — оно выведено расчётом"
    word = "снимок" if observations == 1 else "снимка" if observations < 5 else "снимков"
    if optical == OPTICAL_WEAK:
        if coverage is not None and coverage < MIN_COVERAGE_FOR_STRONG:
            return f"пригодных {word} в окне {observations}, и те закрыты облаками наполовину"
        return f"событие опирается на {observations} пригодный {word}"
    return f"событие измерено: пригодных {word} в окне {observations}"


def _radar_reason(radar: str) -> str:
    if radar == RADAR_AGREES:
        return "радар независимо показывает то же самое"
    if radar == RADAR_SILENT:
        return "радар в эти дни изменений структуры не показывает"
    if radar == RADAR_NO_DATA:
        return "радарных снимков в окне нет — проверить вторым источником нечем"
    return "радар недоступен"
