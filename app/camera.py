"""Zamiana ustawienia kamery 3D na opis tekstowy (ta sama logika co w static/app.js)."""
import math


def describe(az: float, el: float, dist: float, fov: float) -> dict:
    a = abs(((az + 180) % 360) - 180)
    if a <= 22:
        angle = ("przód", "front view")
    elif a <= 67:
        angle = ("3/4", "three-quarter view")
    elif a <= 112:
        angle = ("profil", "side profile view")
    elif a <= 157:
        angle = ("3/4 z tyłu", "rear three-quarter view")
    else:
        angle = ("tył", "back view")

    # Sprawdzone testem (Krea Identity Edit): lagodne "low angle, shot from below" bywa ignorowane,
    # dzialaja mocne opisy z pozycja kamery.
    if el < -35:
        height = ("z dołu (skrajnie)", "extreme worm's-eye view, the camera is on the ground at her feet tilted steeply "
                                      "upward, we look up at the underside of her chin with the sky behind")
    elif el < -15:
        height = ("z dołu", "heroic low-angle shot from ground level looking up at the subject, strong foreshortening, "
                            "the horizon is below the camera, sky behind her head")
    elif el <= 15:
        height = ("poziom oczu", "eye-level")
    elif el <= 50:
        height = ("z góry", "high angle")
    else:
        height = ("z lotu ptaka", "overhead top-down view")

    if dist < 2.2:
        plan = ("zbliżenie twarzy", "close-up on the face")
    elif dist < 3.2:
        plan = ("półzbliżenie", "medium close-up")
    elif dist < 4.5:
        plan = ("plan średni", "medium shot")
    elif dist < 6:
        plan = ("cała postać", "full body shot")
    else:
        plan = ("plan ogólny", "wide shot")

    mm = round(12 / math.tan(math.radians(fov / 2)))
    return {
        "pl": f"{angle[0]}, {height[0]}, {plan[0]}, ok. {mm} mm",
        "en": f"{angle[1]}, {height[1]}, {plan[1]}, {mm}mm lens",
    }
