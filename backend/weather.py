from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


LIGHT_RAIN_THRESHOLD_MM_HR = 5.0
HEAVY_RAIN_THRESHOLD_MM_HR = 10.0


@dataclass(frozen=True)
class WeatherScenario:
    name: str
    precipitation_mm_hr: float
    storm_active: bool = False


SCENARIOS: Dict[str, WeatherScenario] = {
    "clear": WeatherScenario(name="clear", precipitation_mm_hr=0.0, storm_active=False),
    "cloudy": WeatherScenario(name="cloudy", precipitation_mm_hr=0.0, storm_active=False),
    "light_rain": WeatherScenario(name="light_rain", precipitation_mm_hr=3.0, storm_active=False),
    "heavy_rain": WeatherScenario(name="heavy_rain", precipitation_mm_hr=12.0, storm_active=False),
    "thunderstorm": WeatherScenario(name="thunderstorm", precipitation_mm_hr=8.0, storm_active=True),
}


def classify_weather(precipitation_mm_hr: float, storm_active: bool) -> str:
    if storm_active:
        return "thunderstorm"
    if precipitation_mm_hr > HEAVY_RAIN_THRESHOLD_MM_HR:
        return "heavy_rain"
    if precipitation_mm_hr > 0:
        return "light_rain"
    return "clear"


def get_band_multipliers(precipitation_mm_hr: float, storm_active: bool) -> Dict[str, float]:
    if storm_active:
        return {
            "5G_NR": 0.75,
            "LTE_2300": 0.75,
            "LTE_1800": 0.75,
            "LTE_900_700": 0.75,
        }

    if precipitation_mm_hr > HEAVY_RAIN_THRESHOLD_MM_HR:
        return {
            "5G_NR": 0.60,
            "LTE_2300": 0.70,
            "LTE_1800": 0.85,
            "LTE_900_700": 0.95,
        }

    if precipitation_mm_hr > 0:
        return {
            "5G_NR": 0.90,
            "LTE_2300": 0.90,
            "LTE_1800": 0.95,
            "LTE_900_700": 1.00,
        }

    return {
        "5G_NR": 1.00,
        "LTE_2300": 1.00,
        "LTE_1800": 1.00,
        "LTE_900_700": 1.00,
    }


def simulate_weather(scenario_name: str = "clear") -> Dict[str, object]:
    scenario = SCENARIOS.get(scenario_name.lower())
    if scenario is None:
        valid = ", ".join(sorted(SCENARIOS))
        raise ValueError(f"Unknown scenario '{scenario_name}'. Valid scenarios: {valid}")

    condition = classify_weather(
        precipitation_mm_hr=scenario.precipitation_mm_hr,
        storm_active=scenario.storm_active,
    )
    if scenario.name == "cloudy":
        condition = "cloudy"
    multipliers = get_band_multipliers(
        precipitation_mm_hr=scenario.precipitation_mm_hr,
        storm_active=scenario.storm_active,
    )

    return {
        "scenario": scenario.name,
        "weather_conditions": {
            "condition": condition,
            "precipitation_mm_hr": scenario.precipitation_mm_hr,
            "storm_active": scenario.storm_active,
            "multipliers_applied": multipliers,
        },
    }


def apply_weather_penalty(base_score: float, band: str, scenario_name: str = "clear") -> float:
    weather = simulate_weather(scenario_name)
    multipliers = weather["weather_conditions"]["multipliers_applied"]
    multiplier = multipliers.get(band, 1.0)
    adjusted_score = base_score * multiplier
    return round(adjusted_score, 2)


def make_decision(base_score: float, band: str, scenario_name: str = "clear") -> str:
    adjusted_score = apply_weather_penalty(base_score, band, scenario_name)
    if adjusted_score < 25:
        return "Activate emergency protocol"
    if adjusted_score < 60:
        return "Increase caution"
    return "Proceed normally"


if __name__ == "__main__":
    demo_band = "LTE_2300"
    demo_score = 78.0

    for scenario_name in SCENARIOS:
        simulation = simulate_weather(scenario_name)
        adjusted_score = apply_weather_penalty(demo_score, demo_band, scenario_name)
        decision = make_decision(demo_score, demo_band, scenario_name)

        print(f"Scenario: {simulation['scenario']}")
        print(f"Weather: {simulation['weather_conditions']}")
        print(f"Adjusted {demo_band} score: {adjusted_score}")
        print(f"Decision: {decision}")
        print("-" * 40)
