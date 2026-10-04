export interface AscentZone { zone_id: string; name: string; macro_group: string; vertices_px: [number, number][] }

// Direct adapter of configs/maps/ascent.yaml; coordinates remain approximate candidates.
export const ascentZones: AscentZone[] = [
  {
    "zone_id": "attacker_spawn",
    "name": "Attacker Spawn",
    "macro_group": "SPAWN",
    "vertices_px": [
      [
        1442.69,
        1396.55
      ],
      [
        1442.69,
        631.32
      ],
      [
        1738.91,
        631.32
      ],
      [
        1738.91,
        1063.3
      ],
      [
        1961.08,
        1063.3
      ],
      [
        1961.08,
        1260.78
      ],
      [
        1775.94,
        1260.78
      ],
      [
        1775.94,
        1396.55
      ]
    ]
  },
  {
    "zone_id": "a_lobby",
    "name": "A Lobby",
    "macro_group": "A",
    "vertices_px": [
      [
        1158.82,
        631.32
      ],
      [
        1158.82,
        458.53
      ],
      [
        1430.35,
        458.53
      ],
      [
        1430.35,
        631.32
      ]
    ]
  },
  {
    "zone_id": "a_main",
    "name": "A Main",
    "macro_group": "A",
    "vertices_px": [
      [
        911.97,
        767.09
      ],
      [
        911.97,
        100.59
      ],
      [
        1047.74,
        100.59
      ],
      [
        1047.74,
        767.09
      ]
    ]
  },
  {
    "zone_id": "a_site",
    "name": "A Site",
    "macro_group": "A",
    "vertices_px": [
      [
        541.7,
        656.0
      ],
      [
        541.7,
        149.96
      ],
      [
        899.63,
        149.96
      ],
      [
        899.63,
        656.0
      ]
    ]
  },
  {
    "zone_id": "a_defensive_back_site",
    "name": "A defensive / back-site",
    "macro_group": "A",
    "vertices_px": [
      [
        455.3,
        767.09
      ],
      [
        455.3,
        162.31
      ],
      [
        541.7,
        162.31
      ],
      [
        541.7,
        767.09
      ]
    ]
  },
  {
    "zone_id": "mid_bottom",
    "name": "Mid Bottom (defender-side approach in this source orientation)",
    "macro_group": "MID",
    "vertices_px": [
      [
        763.86,
        1137.36
      ],
      [
        763.86,
        890.51
      ],
      [
        924.31,
        890.51
      ],
      [
        924.31,
        1137.36
      ]
    ]
  },
  {
    "zone_id": "mid_top",
    "name": "Mid Top (attacker-side approach in this source orientation)",
    "macro_group": "MID",
    "vertices_px": [
      [
        1158.82,
        1125.02
      ],
      [
        1158.82,
        816.46
      ],
      [
        1405.67,
        816.46
      ],
      [
        1405.67,
        1125.02
      ]
    ]
  },
  {
    "zone_id": "catwalk_a_link",
    "name": "Catwalk / A Link",
    "macro_group": "MID",
    "vertices_px": [
      [
        924.31,
        1050.96
      ],
      [
        924.31,
        779.43
      ],
      [
        1158.82,
        779.43
      ],
      [
        1158.82,
        1050.96
      ]
    ]
  },
  {
    "zone_id": "market_b_link",
    "name": "Market / B Link",
    "macro_group": "MID",
    "vertices_px": [
      [
        541.7,
        1285.47
      ],
      [
        541.7,
        1137.36
      ],
      [
        776.2,
        1137.36
      ],
      [
        776.2,
        1285.47
      ]
    ]
  },
  {
    "zone_id": "b_lobby",
    "name": "B Lobby",
    "macro_group": "B",
    "vertices_px": [
      [
        961.34,
        1606.37
      ],
      [
        961.34,
        1273.12
      ],
      [
        1282.24,
        1273.12
      ],
      [
        1282.24,
        1606.37
      ]
    ]
  },
  {
    "zone_id": "b_main",
    "name": "B Main",
    "macro_group": "B",
    "vertices_px": [
      [
        763.86,
        1581.69
      ],
      [
        763.86,
        1260.78
      ],
      [
        924.31,
        1260.78
      ],
      [
        924.31,
        1581.69
      ]
    ]
  },
  {
    "zone_id": "b_site",
    "name": "B Site",
    "macro_group": "B",
    "vertices_px": [
      [
        418.27,
        1754.48
      ],
      [
        418.27,
        1396.55
      ],
      [
        665.12,
        1396.55
      ],
      [
        665.12,
        1754.48
      ]
    ]
  },
  {
    "zone_id": "b_defensive_back_site",
    "name": "B defensive / back-site",
    "macro_group": "B",
    "vertices_px": [
      [
        294.85,
        1754.48
      ],
      [
        294.85,
        1396.55
      ],
      [
        418.27,
        1396.55
      ],
      [
        418.27,
        1754.48
      ]
    ]
  },
  {
    "zone_id": "defender_spawn",
    "name": "Defender Spawn / rotation area",
    "macro_group": "SPAWN",
    "vertices_px": [
      [
        78.86,
        1026.28
      ],
      [
        78.86,
        767.09
      ],
      [
        294.85,
        767.09
      ],
      [
        294.85,
        1026.28
      ]
    ]
  }
] ;
