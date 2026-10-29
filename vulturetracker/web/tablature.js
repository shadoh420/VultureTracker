/* Native score editor. alphaTab 1.8.4 is a disposable SVG projection, never the song or player. */
(() => {
  'use strict';
  const clone = value => JSON.parse(JSON.stringify(value));
  const isPercussion = track => track?.midi?.bank === 128;
  // TuxGuitar scale catalogue, pinned 2c46e2a1; see web/licenses/TuxGuitar-scales-NOTICE.txt.
  // Entries retain source order and aliases; values are zero-based semitone masks.
  const scaleCatalogue = [
    ["Major Scale", 2741],
    ["Pentatonic Major Scale", 661],
    ["Blues Major Scale", 745],
    ["Minor Scale", 1453],
    ["Melodic Minor Scale", 2733],
    ["Harmonic Minor Scale", 2477],
    ["Pentatonic Minor Scale", 1193],
    ["Blues Minor Scale", 1257],
    ["Augmented Scale", 2457],
    ["Be-Bop Scale", 3765],
    ["Chromatic Scale", 4095],
    ["Whole-Half Scale", 2925],
    ["Half-Whole Scale", 1755],
    ["Whole Tone Scale", 1365],
    ["Augmented Fifth Scale", 2997],
    ["Algerian Scale", 2509],
    ["Arabian Scale", 1397],
    ["Balinese Scale", 395],
    ["Bartok Scale", 1749],
    ["Byzantine Scale", 2483],
    ["Chinese Scale", 661],
    ["Egyptian Scale", 1189],
    ["Enigmatic Scale", 3411],
    ["Spanish Scale", 1459],
    ["Spanish 8 Tone Scale", 1403],
    ["Ethiopian Scale", 1453],
    ["Gypsy Scale", 1715],
    ["Hungarian Gypsy Scale", 1485],
    ["Hindu Scale", 1461],
    ["Iwato Scale", 1123],
    ["Japanese Scale", 419],
    ["Javanese Scale", 1707],
    ["Jewish Scale", 1459],
    ["Hawaiian Scale", 2733],
    ["Hirajoshi Scale", 397],
    ["Hungarian Minor Scale", 2509],
    ["Hungarian Major Scale", 1753],
    ["Kumoi Scale", 419],
    ["Leading Whole Tone Scale", 3413],
    ["Mohammedan Scale", 2477],
    ["Mongolian Scale", 661],
    ["Neapolitan Minor Scale", 2475],
    ["Neapolitan Major Scale", 2731],
    ["Oriental Scale", 1651],
    ["Overtone Scale", 1749],
    ["Pelog Scale", 1163],
    ["Persian Scale", 2419],
    ["Ionian Mode", 2741],
    ["Dorian Mode", 1709],
    ["Phrygian Mode", 1451],
    ["Lydian Mode", 2773],
    ["Mixolydian Mode", 1717],
    ["Aeolian Mode", 1453],
    ["Locrian Mode", 1387],
    ["Aeolian Harmonic Mode", 2477],
    ["Locrian Sharp 6 Mode", 1643],
    ["Major Sharp 5 Mode", 2869],
    ["Dorian Sharp 4 Mode", 1741],
    ["Phrygian Major Mode", 1459],
    ["Lydian Sharp 2 mode", 2777],
    ["Superlocrian Double Flat 7 Mode", 859],
    ["Jazz Minor Mode", 2733],
    ["Dorian b2 Minor Mode", 2731],
    ["Lydian Augmented Minor Mode", 2901],
    ["Lydian Flat 7 Minor Mode", 1749],
    ["Mixolydian Flat 6 Minor Mode", 1461],
    ["Locrian Sharp 2 Minor Mode", 1389],
    ["Superlocrian Minor Mode", 1371],
    ["Pentatonic Majeur Mode", 661],
    ["Pentatonic Mode 2", 1189],
    ["Pentatonic Mode 3", 1321],
    ["Pentatonic Mode 4", 677],
    ["Pentatonic Dominant Mode", 1173],
    ["Pentatonic Minor Mode", 1193],
    ["Altered Pentatonic Mode", 659],
    ["Blues Mode", 745],
    ["Major Arpeggio", 145],
    ["Minor Arpeggio", 137],
    ["Major 7th Major Arpeggio", 2193],
    ["Major 7th Minor Arpeggio", 1169],
    ["Minor 7th Major Arpeggio", 2185],
    ["Minor 7th Minor Arpeggio", 1161],
    ["Major 9th Arpeggio", 1173],
    ["Minor 9th Arpeggio", 1165],
    ["Major 11th Arpeggio", 1205],
    ["Minor 11th Arpeggio", 1197],
    ["Major 13th Arpeggio", 1717],
    ["Minor 13th Arpeggio", 1709],
    ["Augmented Arpeggio", 273],
    ["Diminished Arpeggio", 585],
    ["Gb SCALE: Ionian b5 (Nicolas SLONIMSKY n\u00b01074)", 2677],
    ["Gb SCALE: Dorian b4", 1693],
    ["Gb SCALE: Phrygian b3 (Purva Melakarta n\u00b0 2)", 1447],
    ["Gb SCALE: Lydian b2 (Uttara Melakarta n\u00b0 17, Nicolas SLONIMSKY n\u00b01058)", 2771],
    ["Gb SCALE: Mixolydian b1", 3433],
    ["Gb SCALE: Aeolian b7 (Purva Melakarta n\u00b0 19)", 941],
    ["Gb SCALE: Locian b6", 1259],
    ["Db SCALE: Ionian b2 (Purva Melakarta n\u00b0 17, Nicolas SLONIMSKY n\u00b01055)", 2739],
    ["Db SCALE: Dorian b1", 3417],
    ["Db SCALE: Phrygian b7 (Purva Melakarta n\u00b0 7)", 939],
    ["Db SCALE: Lydian b6 (Uttara Melakarta n\u00b0 27)", 2517],
    ["Db SCALE: Mixolydian b5 (Nicolas SLONIMSKY n\u00b01073)", 1653],
    ["Db SCALE: Aeolian b4", 1437],
    ["Db SCALE: Locian b3", 1383],
    ["Ab SCALE: Ionian b6 (Purva Melakarta n\u00b0 27, Nicolas SLONIMSKY n\u00b01079)", 2485],
    ["Ab SCALE: Dorian b5 (Nicolas SLONIMSKY n\u00b01072)", 1645],
    ["Ab SCALE: Phrygian b4 (Nicolas SLONIMSKY n\u00b01066)", 1435],
    ["Ab SCALE: Lydian b3 (Uttara Melakarta n\u00b0 23, Nicolas SLONIMSKY n\u00b01065)", 2765],
    ["Ab SCALE: Mixolydian b2 (Purva Melakarta n\u00b0 16, Nicolas SLONIMSKY n\u00b01054)", 1715],
    ["Ab SCALE: Aeolian b1", 2905],
    ["Ab SCALE: Locian b7", 875],
    ["Eb SCALE: Ionian b3 (Purva Melakarta n\u00b0 23, Nicolas SLONIMSKY n\u00b01042, Melodic Minor Scale)", 2733],
    ["Eb SCALE: Dorian b2 (Purva Melakarta n\u00b0 10, Nicolas SLONIMSKY n\u00b01037)", 1707],
    ["Eb SCALE: Phrygian b1 (Nicolas SLONIMSKY n\u00b01066, Lydien Augment\u00e9)", 2901],
    ["Eb SCALE: Lydian b7 (Uttara Melakarta n\u00b0 28, Nicolas SLONIMSKY n\u00b01046, Bartok Scale)", 1749],
    ["Eb SCALE: Mixolydian b6 (Purva Melakarta n\u00b0 26, Nicolas SLONIMSKY n\u00b01043)", 1461],
    ["Eb SCALE: Aeolian b5 (Nicolas SLONIMSKY n\u00b01039)", 1389],
    ["Eb SCALE: Locian b4 (Nicolas SLONIMSKY n\u00b01034, Alt\u00e9r\u00e9)", 1371],
    ["G# SCALE: Ionian #5", 2869],
    ["G# SCALE: Dorian #4 (Uttara Melakarta n\u00b0 22, Nicolas SLONIMSKY n\u00b01064)", 1741],
    ["G# SCALE: Phrygian #3 (Purva Melakarta n\u00b014, Nicolas SLONIMSKY n\u00b01053, Spanish Scale, Jewish Scale)", 1459],
    ["G# SCALE: Lydian #2 (Uttara Melakarta n\u00b0 35)", 2777],
    ["G# SCALE: Mixolydian #1", 859],
    ["G# SCALE: Aeolian #7 (Purva Melakarta n\u00b0 21, Nicolas SLONIMSKY n\u00b01078, Harmonic Minor Scale)", 2477],
    ["G# SCALE: Locian #6 (Nicolas SLONIMSKY n\u00b01070)", 1643],
    ["D# SCALE: Ionian #2 (Purva Melakarta n\u00b0 35, Nicolas SLONIMSKY n\u00b01052)", 2745],
    ["D# SCALE: Dorian #1", 855],
    ["D# SCALE: Phrygian #7 (Purva Melakarta n\u00b0 9, Napolitain Mineur)", 2475],
    ["D# SCALE: Lydian #6 (Uttara Melakarta n\u00b0 30)", 3285],
    ["D# SCALE: Mixolydian #5", 1845],
    ["D# SCALE: Aeolian #4 (Uttara Melakarta n\u00b0 20, Nicolas SLONIMSKY n\u00b01063)", 1485],
    ["D# SCALE: Locian #3", 1395],
    ["A# SCALE: Ionian #6 (Purva Melakarta n\u00b0 30)", 3253],
    ["A# SCALE: Dorian #5", 1837],
    ["A# SCALE: Phrygian #4 (Uttara Melakarta n\u00b0 8, Nicolas SLONIMSKY n\u00b01060)", 1483],
    ["A# SCALE: Lydian #3", 2789],
    ["A# SCALE: Mixolydian #2 (Purva Melakarta n\u00b0 34, Nicolas SLONIMSKY n\u00b01051)", 1721],
    ["A# SCALE: Aeolian #1", 727],
    ["A# SCALE: Locian #7 (Nicolas SLONIMSKY n\u00b01076)", 2411],
    ["C#Eb SCALE: Ionian #1b3", 1367],
    ["C#Eb SCALE: Dorian #7b2 (Purva Melakarta n\u00b0 11, Nicolas SLONIMSKY n\u00b01038, Napolitain Majeur)", 2731],
    ["C#Eb SCALE: Phrygian #6b1 (Leading Whole Tone)", 3413],
    ["C#Eb SCALE: Lydian #5b7", 1877],
    ["C#Eb SCALE: Mixolydian #4b6 (Uttara Melakarta n\u00b0 26, Lydien Mineur)", 1493],
    ["C#Eb SCALE: Aeolian #3b5(Locrien Majeur)", 1397],
    ["C#Eb SCALE: Locrian #2b4", 1373],
    ["GbAb SCALE: Ionian b5b6", 2421],
    ["GbAb SCALE: Dorian b4b5", 1629],
    ["GbAb SCALE: Phrygian b3b4", 1431],
    ["GbAb SCALE: Lydian b2b3 (Uttara Melakarta n\u00b0 11, Nicolas SLONIMSKY n\u00b01062)", 2763],
    ["GbAb SCALE: Mixolydian b1b2", 3429],
    ["GbAb SCALE: Aeolian b7b1", 1881],
    ["GbAb SCALE: Locrian b6b7", 747],
    ["C#Gb SCALE: Ionian #1b5", 1339],
    ["C#Gb SCALE: Dorian #7b4", 2717],
    ["C#Gb SCALE: Phrygian #6b3 (Purva Melakarta n\u00b0 4)", 1703],
    ["C#Gb SCALE: Lydian #5b2", 2899],
    ["C#Gb SCALE: Mixolydian #4b1", 3497],
    ["C#Gb SCALE: Aeolian #3b7 (Purva Melakarta n\u00b0 25)", 949],
    ["C#Gb SCALE: Locrian #2b6", 1261],
    ["AbD# SCALE: Ionian #2b6 (Purva Melakarta n\u00b0 33)", 2489],
    ["AbD# SCALE: Dorian #1b5", 823],
    ["AbD# SCALE: Phrygian #7b4 (Nicolas SLONIMSKY n\u00b01086)", 2459],
    ["AbD# SCALE: Lydian #6b3 (Uttara Melakarta n\u00b0 24)", 3277],
    ["AbD# SCALE: Mixolydian #5b2 (Nicolas SLONIMSKY n\u00b01080)", 1843],
    ["AbD# SCALE: Aeolian #4b1", 2969],
    ["AbD# SCALE: Locrian #3b7", 883],
    ["A#Eb SCALE: Ionian #6b3 (Purva Melakarta n\u00b0 24)", 3245],
    ["A#Eb SCALE: Dorian #5b2", 1835],
    ["A#Eb SCALE: Phrygian #4b1", 2965],
    ["A#Eb SCALE: Lydian #3b7", 1765],
    ["A#Eb SCALE: Mixolydian #2b6 (Purva Melakarta n\u00b0 32, Nicolas SLONIMSKY n\u00b01050)", 1465],
    ["A#Eb SCALE: Aeolian #1b5", 695],
    ["A#Eb SCALE: Locrian #7b4 (Superlocrien Harmonique, Nicolas SLONIMSKY n\u00b01075)", 2395],
    ["G#Db SCALE: Ionian #5b2 (Nicolas SLONIMSKY n\u00b01081)", 2867],
    ["G#Db SCALE: Dorian #4b1", 3481],
    ["G#Db SCALE: Phrygian #3b7 (Purva Melakarta n\u00b0 13)", 947],
    ["G#Db SCALE: Lydian #2b6 (Uttara Melakarta n\u00b0 33)", 2521],
    ["G#Db SCALE: Mixolydian #1b5", 827],
    ["G#Db SCALE: Aeolian #7b4 (Nicolas SLONIMSKY n\u00b01087)", 2461],
    ["G#Db SCALE: Locrian #6b3", 1639],
    ["G#Eb SCALE: Ionian #5b3 (Nohkan)", 2861],
    ["G#Eb SCALE: Dorian #4b2 (Uttara Melakarta n\u00b0 10, Nicolas SLONIMSKY n\u00b01061)", 1739],
    ["G#Eb SCALE: Phrygian #3b1", 2917],
    ["G#Eb SCALE: Lydian #2b7 (Uttara Melakarta n\u00b0 34, Hongrois Majeur)", 1753],
    ["G#Eb SCALE: Mixolydian #1b6", 731],
    ["G#Eb SCALE: Aeolian #7b5 (Nicolas SLONIMSKY n\u00b01077)", 2413],
    ["G#Eb SCALE: Locrian #6b4 (Nicolas SLONIMSKY n\u00b01069)", 1627],
    ["G#D# SCALE: Ionian #5#2", 2873],
    ["G#D# SCALE: Dorian #4#1", 871],
    ["G#D# SCALE: Phrygian #3#7 (Purva Melakarta n\u00b0 15, Nicolas SLONIMSKY n\u00b01082)", 2483],
    ["G#D# SCALE: Lydian #2#6 (Uttara Melakarta n\u00b0 36)", 3289],
    ["G#D# SCALE: Mixolydian #1#5", 923],
    ["G#D# SCALE: Aeolian #7#4 (Uttara Melakarta n\u00b0 21, Nicolas SLONIMSKY n\u00b01085)", 2509],
    ["G#D# SCALE: Locrian #6#3", 1651],
    ["AbC# SCALE: Ionian b6#1 (Absidioles 4)", 1243],
    ["AbC# SCALE: Dorian b5#7", 2669],
    ["AbC# SCALE: Phrygian b4#6 (Nicolas SLONIMSKY n\u00b01067, Absidioles 3)", 1691],
    ["AbC# SCALE: Lydian b3#5", 2893],
    ["AbC# SCALE: Mixolydian b2#4 (Uttara Melakarta n\u00b0 16, Nicolas SLONIMSKY n\u00b01057)", 1747],
    ["AbC# SCALE: Aeolian b1#3", 2921],
    ["AbC# SCALE: Locrian b7#2 (Blue Scale)", 877],
    ["G#A# SCALE: Ionian #5#6", 3381],
    ["G#A# SCALE: Dorian #4#5", 1869],
    ["G#A# SCALE: Phrygian #3#4 (Uttara Melakarta n\u00b0 14, Nicolas SLONIMSKY n\u00b01056)", 1491],
    ["G#A# SCALE: Lydian #2#3", 2793],
    ["G#A# SCALE: Mixolydian #1#2", 861],
    ["G#A# SCALE: Aeolian #7#1", 1239],
    ["G#A# SCALE: Locrian #6#5 (Nicolas SLONIMSKY n\u00b01071)", 2667],
    ["DbGb SCALE: Ionian b2b5", 2675],
    ["DbGb SCALE: Dorian b1b4", 3385],
    ["DbGb SCALE: Phrygian b7b3 (Purva Melakarta n\u00b0 1)", 935],
    ["DbGb SCALE: Lydian b6b2 (Uttara Melakarta n\u00b0 15, Nicolas SLONIMSKY n\u00b01083, Composite)", 2515],
    ["DbGb SCALE: Mixolydian b5b1", 3305],
    ["DbGb SCALE: Aeolian b4b7", 925],
    ["DbGb SCALE: Locrian b3b6", 1255],
    ["D#A# SCALE: Ionian #2#6 (Purva Melakarta n\u00b0 36)", 3257],
    ["D#A# SCALE: Dorian #1#5", 919],
    ["D#A# SCALE: Phrygian #7#4 (Uttara Melakarta n\u00b0 9, Nicolas SLONIMSKY n\u00b01084, Tod\u00ee)", 2507],
    ["D#A# SCALE: Lydian #6#3", 3301],
    ["D#A# SCALE: Mixolydian #5#2", 1849],
    ["D#A# SCALE: Aeolian #4#1", 743],
    ["D#A# SCALE: Locrian #3#7", 2419],
    ["GbD# SCALE: Ionian b5#2", 2681],
    ["GbD# SCALE: Dorian b4#1", 847],
    ["GbD# SCALE: Phrygian b3#7 (Purva Melakarta n\u00b0 3)", 2471],
    ["GbD# SCALE: Lydian b2#6 (Uttara Melakarta n\u00b0 18)", 3283],
    ["GbD# SCALE: Mixolydian b1#5", 3689],
    ["GbD# SCALE: Aeolian b7#4 (Uttara Melakarta n\u00b0 19)", 973],
    ["GbD# SCALE: Locrian b6#3", 1267],
    ["A#Db SCALE: Ionian #6b2 (Purva Melakarta n\u00b0 18)", 3251],
    ["A#Db SCALE: Dorian #5b1", 3673],
    ["A#Db SCALE: Phrygian #4b7 (Uttara Melakarta n\u00b0 7)", 971],
    ["A#Db SCALE: Lydian #3b6", 2533],
    ["A#Db SCALE: Mixolydian #2b5", 1657],
    ["A#Db SCALE: Aeolian #1b4", 719],
    ["A#Db SCALE: Locrian #7b3", 2407],
    ["A#Gb SCALE: Ionian #6b5", 3189],
    ["A#Gb SCALE: Dorian #5b4", 1821],
    ["A#Gb SCALE: Phrygian #4b3 (Uttara Melakarta n\u00b0 2)", 1479],
    ["A#Gb SCALE: Lydian #3b2", 2787],
    ["A#Gb SCALE: Mixolydian #2b1", 3441],
    ["A#Gb SCALE: Aeolian #1b7", 471],
    ["A#Gb SCALE: Locrian #7b6", 2283],
    ["GbA#C# SCALE: Phrygian b3#4#6 (Uttara Melakarta n\u00b0 4)", 1735],
    ["GbA#C# SCALE: Locrian b6#7#3", 2285],
    ["D omitted Ab added SCALE: Ionian omit2 addb6", 2993],
    ["GbA#D# SCALE: Phrygian b3#4#7 (Uttara Melakarta n\u00b0 3)", 2503],
    ["EbGbA# SCALE: Aeolian b5b7#1", 439],
    ["GbA#Db SCALE: Phrygian b3#4b7", 967],
    ["B#C#Gb SCALE: Dorian #6#7b4", 3229],
    ["B#C#Gb SCALE: Aeolian #2#3b7", 953],
    ["DbEbb SCALE: Ionian b2bb3 (Purva Melakarta n\u00b0 5)", 2727],
    ["DbEbb SCALE: Dorian b1bb2 (Enigmatic)", 3411],
    ["DbEbb SCALE: Phrygian b7bb1", 3753],
    ["DbEbb SCALE: Lydian b6bb7 (Uttara Melakarta n\u00b0 25)", 981],
    ["DbEbb SCALE: Mixolydian b5bb6", 1269],
    ["C#D#Ab SCALE: Ionian #1#2b6", 1245],
    ["C#D#Ab SCALE: Phrygian 6#7#4b (Nicolas SLONIMSKY n\u00b01068)", 2715],
    ["C#D#Ab SCALE: Aeolian #3#4b1", 2985],
    ["GbAbC# SCALE: Ionian b5b6#1", 1211],
    ["GbAbC# SCALE: Locrian b6b7#2", 749],
    ["G#A#Eb SCALE: Lydian #2#3b7", 1769],
    ["G#A#Db SCALE: Phrygian #3#4b7 (Uttara Melakarta n\u00b0 13)", 979],
    ["G#A#Db SCALE: Lydian #2#3b6", 2537],
    ["D#GbAb SCALE: Lydian #6b2b3 (Uttara Melakarta n\u00b0 12)", 3275],
    ["D#GbAb SCALE: Aeolian #4b7b1", 1945],
    ["A#C#Eb SCALE: Mixolydian #2#4b6 (Uttara Melakarta n\u00b0 32)", 1497],
    ["A#DbEb SCALE: Ionian #6b2b3 (Purva Melakarta n\u00b0 12)", 3243],
    ["A#DbEb SCALE: Aeolian #1b4b5", 687],
    ["A#B#C#Eb SCALE: Mixolydian #2#3#4b6", 1513],
    ["C#D#GbAb SCALE: Locrian #2#3b6b7", 757],
    ["GbA#C#D# SCALE: Locrian b6#7#2#3", 2293],
    ["GbA#C#D# SCALE: Phrygian b3#4#6#7 (Uttara Melakarta n\u00b0 5)", 2759],
    ["EbFbGbb SCALE: Aeolian b5b6bb7", 493],
  ];
  // TGDrumMap at 2c46e2a1: position, head family, optional modifier.
  // Native lanes are not TG's suggested strings and never come from this map.
  const drumMap = {
    35:[7,'round'],36:[6,'round'],37:[2,'circled'],38:[2,'round'],40:[2,'round'],
    42:[-2,'x'],46:[-2,'x','open'],44:[8,'x'],
    49:[-3,'effect'],57:[-4,'effect'],55:[-5,'effect'],52:[-5,'circleX'],
    51:[-1,'x'],59:[1,'x'],53:[-1,'diamond'],
    41:[5,'round'],43:[4,'round'],45:[3,'round'],47:[1,'round'],48:[0,'round'],50:[-1,'round'],
    54:[3,'triangle'],56:[0,'triangle'],31:[3,'x'],77:[2,'triangle'],76:[1,'triangle'],
    81:[-3,'triangle'],80:[-3,'triangle','closed']
  };
  function drumArticulations() {
    const m = alphaTab.model, f = m.MusicFontSymbol;
    const heads = {round:['NoteheadBlack','NoteheadHalf','NoteheadWhole'],
      circled:['NoteheadCircledBlack','NoteheadCircledHalf','NoteheadCircledWhole'],
      x:['NoteheadXBlack'], effect:['NoteheadXOrnate'], circleX:['NoteheadCircleX'],
      diamond:['NoteheadDiamondBlack','NoteheadDiamondHalf','NoteheadDiamondWhole'],
      triangle:['NoteheadTriangleUpBlack','NoteheadTriangleUpHalf','NoteheadTriangleUpWhole']};
    const make = (key, closed = false) => {
      const [position, shape, modifier] = drumMap[key] || [-1,'round'];
      const h = heads[shape].map(name => f[name]);
      return new m.InstrumentArticulation(`Drum key ${key}`, position + 1, key,
        h[0], h[1] ?? h[0], h[2] ?? h[0],
        closed || modifier === 'closed' ? f.NoteheadPlusBlack : modifier === 'open' ? f.FretboardO : f.None,
        m.TechniqueSymbolPlacement.Above, closed ? 101 : key);
    };
    return [...Array.from({length:101}, (_, key) => make(key)), make(42, true)];
  }
  const gcd = (a, b) => b ? gcd(b, a % b) : Math.abs(a);
  const rat = (n, d = 1) => { const g = gcd(n, d) || 1; return [n / g, d / g]; };
  const add = (a, b) => rat(a[0] * b[1] + b[0] * a[1], a[1] * b[1]);
  const sub = (a, b) => rat(a[0] * b[1] - b[0] * a[1], a[1] * b[1]);
  const cmp = (a, b) => a[0] * b[1] - b[0] * a[1];
  const num = a => a[0] / a[1];
  const rowPair = row => Array.isArray(row) ? row : [row, 1];
  const sameRow = (a, b) => a != null && b != null && cmp(rowPair(a), rowPair(b)) === 0;
  function chordFirstFret(chord) {
    const positive = chord.frets.filter(f => f > 0);
    return chord.first_fret || (positive.length ? Math.max(1, Math.min(...positive)) : 1);
  }
  const tapSlapPop = [['tapping', 'Tap', 'tap'], ['slapping', 'Slap', 'slap'], ['popping', 'Pop', 'pop']];
  function drawChordShape(preview, chord) {
    preview.replaceChildren();
    const first = chordFirstFret(chord), count = chord.frets.length, width = 80 + 24 * Math.max(1, count - 1);
    preview.setAttribute('viewBox', `0 0 ${width} 180`); preview.style.width = width + 'px';
    const node = (tag, attrs, value) => {
      const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
      for (const [key, val] of Object.entries(attrs)) el.setAttribute(key, String(val));
      if (value != null) el.textContent = value; preview.append(el);
    };
    node('text', {x: 2, y: 55, fill: 'currentColor', 'font-size': 12}, first + ' fr');
    for (let fret = 0; fret <= 5; fret++) node('line', {x1: 44, x2: 44 + 24 * Math.max(1, count - 1),
      y1: 40 + fret * 20, y2: 40 + fret * 20, stroke: 'currentColor', 'stroke-width': fret === 0 && first === 1 ? 3 : 1});
    chord.frets.forEach((fret, i) => {
      const x = 44 + (count - 1 - i) * 24;
      node('line', {x1: x, x2: x, y1: 40, y2: 140, stroke: 'currentColor'});
      node('text', {x, y: 160, fill: 'currentColor', 'text-anchor': 'middle', 'font-size': 11}, i + 1);
      if (fret <= 0) node('text', {x, y: 28, fill: 'currentColor', 'text-anchor': 'middle', 'data-string': i + 1, 'data-fret': fret}, fret < 0 ? 'X' : 'O');
      else node('circle', {cx: x, cy: 40 + (fret - first + .5) * 20, r: 5, fill: 'currentColor', 'data-string': i + 1, 'data-fret': fret});
    });
  }
  // Score positions are quarter-note units; written.value is the usual denominator.
  const duration = w => rat(4 * (2 ** ((w.dots || 0) + 1) - 1) * (w.tuplet || [1, 1])[1],
    w.value * 2 ** (w.dots || 0) * (w.tuplet || [1, 1])[0]);
  const divisions = [[1, 1], [3, 2], [5, 4], [6, 4], [7, 4], [9, 8], [10, 8], [11, 8], [12, 8], [13, 8]];
  const spellings = divisions.flatMap(tuplet => [0, 1, 2].flatMap(dots => [1, 2, 4, 8, 16, 32, 64].map(value => ({value, dots, tuplet}))));
  function spellSpan(length, preferred) {
    if (preferred) {
      const d = duration(preferred), count = length[0] * d[1] / (length[1] * d[0]);
      if (Number.isInteger(count) && count > 0 && count <= 128) return Array.from({length: count}, () => preferred);
    }
    const exact = spellings.find(w => cmp(duration(w), length) === 0);
    if (exact) return [exact];
    // Only choose values on this span's exact rational grid. This terminates
    // without inventing ratios such as 12:1 to describe an ordinary short rest.
    const usable = spellings.filter(w => length[1] % duration(w)[1] === 0).sort((a, b) => cmp(duration(b), duration(a)));
    const out = []; let remaining = length;
    while (remaining[0] > 0 && out.length < 256) {
      const w = usable.find(w => cmp(duration(w), remaining) <= 0);
      if (!w) throw new Error(`Cannot engrave exact span ${length.join('/')} with supported written durations.`);
      out.push(w); remaining = sub(remaining, duration(w));
    }
    if (remaining[0]) throw new Error('This span needs too many written rests.');
    return out;
  }
  const uid = prefix => prefix + '-' + crypto.randomUUID();
  const text = (tag, value, cls) => { const e = document.createElement(tag); e.textContent = value; if (cls) e.className = cls; return e; };
  const readPosition = value => { const m = /^(\d+)(?:\/(\d+))?$/.exec(value.trim()); if (!m || +(m[2] || 1) === 0) throw new Error('Use a nonnegative integer or fraction, such as 1/3.'); return rat(+m[1], +(m[2] || 1)); };
  function keySpelling(pitch, fifths = 0) {
    // TuxGuitar 2.1.0 TGMusicKeyUtils: the extreme keys also spell B#/E# and Cb/Fb.
    const sharp = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    const flat = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'];
    if (fifths >= 6) sharp[5] = 'E#'; if (fifths === 7) sharp[0] = 'B#';
    if (fifths <= -6) flat[11] = 'Cb'; if (fifths === -7) flat[4] = 'Fb';
    const value = (fifths < 0 ? flat : sharp)[pitch % 12];
    return {step: value[0], alter: value[1] === '#' ? 1 : value[1] === 'b' ? -1 : 0};
  }
  const scaleRoots = ['C', 'C#', 'Db', 'D', 'D#', 'Eb', 'E', 'F', 'F#', 'Gb', 'G', 'G#', 'Ab', 'A', 'A#', 'Bb', 'B'];
  const rootPitch = name => ({C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11}[name[0]] + (name[1] === '#' ? 1 : name[1] === 'b' ? -1 : 0) + 12) % 12;
  const scaleHas = (mask, root, pitch) => !!(mask & (1 << ((pitch - root + 120) % 12)));
  const spellingText = s => s.step + ({'-2': 'bb', '-1': 'b', 0: '', 1: '#', 2: '##'}[s.alter || 0]);
  // Adapted from TGMusicKeyUtils.getKeySignature/getNbAccidentals (LGPL-2.1).
  // Keep the source's candidate order and tie break; see TuxGuitar-scales-NOTICE.txt.
  function scaleFifths(mask, name) {
    const pitch = rootPitch(name);
    const count = fifths => {
      if (name.includes('#') && fifths < 0 || name.includes('b') && fifths >= 0) return -1;
      const letters = new Set(), altered = (fifths < 0 ? 'BEADGCF' : 'FCGDAEB').slice(0, Math.abs(fifths));
      let total = 0;
      for (let i = 0; i < 12; i++) if (mask & (1 << i)) {
        const s = keySpelling((pitch + i) % 12, fifths);
        if (letters.has(s.step)) return -1;
        letters.add(s.step);
        if (s.alter !== (altered.includes(s.step) ? Math.sign(fifths) : 0)) total++;
      }
      return total;
    };
    if (count(0) === 0) return 0;
    let best = 0, minimum = 8;
    for (let i = 7; i > 0; i--) for (const fifths of [-i, i]) {
      const value = count(fifths);
      if (value >= 0 && value <= minimum) { minimum = value; best = fifths; }
    }
    return best;
  }
  const fretboardDefaults = {open: false, root: 'C', scale: -1, direction: 'right', noteText: false, scaleText: true,
    spacing: 28, font: 'system-ui', size: 12, bold: true, italic: false,
    background: '#000000', strings: '#e3d9d9', points: '#c0c0c0', notes: '#2a5580', scaleColor: '#802020'};
  function fretboardPreferences(value) {
    const p = {...fretboardDefaults};
    if (!value || typeof value !== 'object') return p;
    for (const k of ['open', 'noteText', 'scaleText', 'bold', 'italic']) if (typeof value[k] === 'boolean') p[k] = value[k];
    for (const k of ['background', 'strings', 'points', 'notes', 'scaleColor']) if (/^#[0-9a-f]{6}$/i.test(value[k])) p[k] = value[k];
    for (const [k, min, max] of [['spacing', 20, 60], ['size', 8, 24], ['scale', -1, scaleCatalogue.length - 1]])
      if (Number.isInteger(value[k]) && value[k] >= min && value[k] <= max) p[k] = value[k];
    if (scaleRoots.includes(value.root)) p.root = value.root;
    if (['left', 'right'].includes(value.direction)) p.direction = value.direction;
    if (typeof value.font === 'string' && value.font.length <= 80 && value.font.trim()) p.font = value.font;
    return p;
  }
  const accidentalMode = spelling => {
    const m = alphaTab.model.NoteAccidentalMode;
    return spelling ? {'-2': m.ForceDoubleFlat, '-1': m.ForceFlat, 0: m.ForceNatural, 1: m.ForceSharp, 2: m.ForceDoubleSharp}[spelling.alter || 0] : m.Default;
  };

  function displayGroups(ranges, from, to) {
    for (let start = from; cmp(start, to) < 0; start = add(start, [4, 1])) ranges.push({from: start,
      to: cmp(add(start, [4, 1]), to) > 0 ? to : add(start, [4, 1]), meter: [4, 4], authored: false});
  }
  const atOccurrence = (p, view, pattern, occurrence = view.score?.order_ids?.[view.order]) =>
    (p.pattern_name ?? p.pattern) === pattern && (p.occurrence == null || p.occurrence === occurrence);
  function resolvedBeats(view, pattern, occurrence = view.score?.order_ids?.[view.order]) {
    const positions = new Map((view.positions || []).filter(p => p.kind === 'note' && atOccurrence(p, view, pattern, occurrence)).map(p => [p.note, p]));
    const source = view.score?.patterns?.[pattern]?.beats || [], cohorts = new Map();
    const lyricKey = b => JSON.stringify([b.track, b.beat ?? b.id, b.voice || 0]);
    const lyrics = new Map((view.lyrics?.anchors || []).filter(a => a.occurrence === occurrence && a.pattern === pattern)
      .map(a => [lyricKey(a), a.display_text]));
    const cohortKey = b => JSON.stringify([b.track, rat(...b.at), b.cohort || 0]);
    for (const b of source) {
      const key = cohortKey(b), shared = cohorts.get(key) || {};
      for (const field of ['stroke', 'pick_stroke', 'chord']) if (b[field] != null) shared[field] = b[field];
      cohorts.set(key, shared);
    }
    // Sparse authored metadata belongs to both voices; only this disposable
    // view inherits it. Edits still clone the original beat and clear with null.
    return source.map(b => ({...b, ...cohorts.get(cohortKey(b)), sourceOccurrence: occurrence,
      lyricLabel: lyrics.get(lyricKey(b)), voice: b.voice || 0, notes: b.notes.map(n => {
      const p = positions.get(n.id);
      return p ? {...n, string: p.string, fret: p.fret} : n;
    })}));
  }
  function chordNoteImpact(view, pattern, beatId, chord) {
    const beats = resolvedBeats(view, pattern), beat = beats.find(b => b.id === beatId);
    if (!beat) throw new Error('The selected beat no longer exists. Reopen the diagram.');
    const cohort = beats.filter(b => b.track === beat.track && cmp(b.at, beat.at) === 0 && (b.cohort || 0) === (beat.cohort || 0));
    const strings = chord.frets.flatMap((fret, i) => fret >= 0 ? [i + 1] : []);
    const others = cohort.filter(b => b.id !== beat.id).flatMap(b => b.notes.map(n => ({...n, voice: b.voice})));
    const unresolved = strings.length ? others.filter(n => n.string == null) : [];
    const affected = others.filter(n => strings.includes(n.string));
    const removed = new Set([...beat.notes, ...affected].map(n => n.id));
    const occurrences = new Set(view.score.order_ids.filter((id, i) => String(view.orders[i]) === pattern));
    const ties = (view.score.ties || []).filter(t => [t.from, t.to].some(p => occurrences.has(p.occurrence) && removed.has(p.note)));
    return {beat, strings, affected, unresolved, ties, uses: occurrences.size,
      noOp: !strings.length && cohort.every(b => !b.notes.length)};
  }
  function engravingCurve(curve, from, to, scale = 1) {
    const points = curve?.points || [];
    if (!points.length) return [];
    const valueAt = x => {
      let left = points[0];
      for (const right of points) {
        if (right.position > x) return left.position >= x ? left.value :
          left.value + (right.value - left.value) * (x - left.position) / (right.position - left.position);
        left = right;
      }
      return left.value;
    };
    const clipped = points.filter(p => p.position >= from && p.position <= to).map(p => ({...p}));
    if (from > 0 && !clipped.some(p => p.position === from)) clipped.unshift({position: from, value: valueAt(from)});
    if (to < 12 && !clipped.some(p => p.position === to)) clipped.push({position: to, value: valueAt(to)});
    return clipped.map(p => new alphaTab.model.BendPoint((p.position - from) * 60 / (to - from), p.value * scale));
  }
  // Both the editor and print view use the same notation projection. All objects
  // below are disposable alphaTab objects; native score data is never changed.
  const graceLabel = (grace, drums = false) => `Grace ${drums ? 'drum key' : 'fret'} ${grace.fret}, 1/${grace.value}, velocity ${grace.velocity}, ${grace.on_beat ? 'on beat' : 'before beat'}${grace.dead ? ', dead' : ''}${grace.transition && grace.transition !== 'none' ? `, ${grace.transition} (notation only)` : ''}`;
  const MEASURE_ACTIONS = ['measure_add', 'measure_remove', 'measure_clean', 'measure_paste', 'measure_meter', 'measure_move', 'measure_unique', 'prepare_measures'];
  function measureRanges(view, occurrence) {
    const offsets = new Map(); let total = [0, 1];
    view.orders.forEach((name, index) => {
      const step = view.score.patterns[name]?.row_step || view.row_step,
        length = rat(view.rows[view.pattern_names.indexOf(String(name))] * step[0], step[1]);
      offsets.set(view.score.order_ids[index], {at: total, end: add(total, length)}); total = add(total, length);
    });
    const own = offsets.get(occurrence), point = p => add(offsets.get(p.occurrence).at, p.at);
    return (view.score.measures || []).map(m => {
      const start = point(m.from), end = point(m.to);
      return {...m, from: sub(cmp(start, own.at) < 0 ? own.at : start, own.at),
        to: sub(cmp(end, own.end) > 0 ? own.end : end, own.at), authored: true,
        continuation: cmp(start, own.at) < 0, continues: cmp(end, own.end) > 0};
    }).filter(r => cmp(r.to, r.from) > 0).sort((a, b) => cmp(a.from, b.from));
  }
  const tempoUnits = new WeakMap(), tempoEffects = new WeakSet();
  const unitQuarterTempo = unit => {
    const quarter = Math.floor(unit.value * 4 / unit.base);
    return unit.dotted ? Math.floor(3 * quarter / 2) : quarter;
  };
  function notationTempos(score, ranges, view, origin = [0, 1]) {
    const changes = view.tempos || [{at: [0, 1], bpm: view.tempo}];
    score.tempoUnitWarnings = [];
    let next = 0, current = view.tempo;
    ranges.forEach((range, i) => {
      const from = add(origin, range.from), to = add(origin, range.to);
      while (next < changes.length && cmp(changes[next].at, from) < 0) current = changes[next++].bpm;
      const points = (i === 0 || range.tempo_unit || ranges[i - 1]?.tempo_unit) &&
        (next === changes.length || cmp(changes[next].at, from) !== 0) ? [{at: from, bpm: current}] : [];
      while (next < changes.length && cmp(changes[next].at, to) < 0) { const point = changes[next++]; points.push(point); current = point.bpm; }
      for (const point of points) {
        const ratio = num(sub(point.at, from)) / num(sub(to, from));
        const tempo = alphaTab.model.Automation.buildTempoAutomation(false, ratio, point.bpm, 2);
        const unit = ratio === 0 ? range.tempo_unit : null;
        // TG uses integer division twice, so 61 dotted quarters really is 91 BPM.
        if (unit && unitQuarterTempo(unit) === point.bpm) tempoUnits.set(tempo, unit);
        else if (unit) score.tempoUnitWarnings.push(`Bar ${i + 1}: written tempo is stale; showing ${point.bpm} quarter notes per minute. Set its beat unit again.`);
        score.masterBars[i].tempoAutomations.push(tempo);
      }
    });
  }

  function registerTempoEngraving() {
    for (const renderer of alphaTab.Environment.defaultRenderers) for (const band of renderer.effectBands) {
      const effect = band.effect;
      if (effect.notationElement !== alphaTab.NotationElement.EffectTempo || tempoEffects.has(effect)) continue;
      tempoEffects.add(effect);
      const create = effect.createNewGlyph, measure = document.createElement('canvas').getContext('2d');
      effect.createNewGlyph = function(renderer, beat) {
        const glyph = create.call(this, renderer, beat);
        const tempos = beat.voice.bar.masterBar.tempoAutomations.filter(t => t.isVisible);
        if (!tempos.some(t => tempoUnits.has(t))) return glyph;
        const resources = renderer.resources, engraving = resources.engravingSettings, scale = engraving.tempoNoteScale;
        // SMuFL metronome marks in the bundled Bravura font, drawn by the native
        // canvas. The automation's quarter-BPM value remains the playback truth.
        const displayScale = renderer.settings.display.scale;
        measure.font = `${engraving.musicFontSize * scale * displayScale}px ${resources.smuflFontFamilyName}`;
        const marks = tempos.map(tempo => {
          const unit = tempoUnits.get(tempo) || {base: 4, value: tempo.value};
          const symbols = [unit.base === 1 ? 0xeca2 : 0xeca1 + 2 * Math.log2(unit.base)];
          if (unit.dotted) symbols.push(0xecb7);
          const measured = measure.measureText(String.fromCodePoint(...symbols));
          const ink = {width: Math.max(measured.width, measured.actualBoundingBoxRight) / displayScale,
            actualBoundingBoxAscent: measured.actualBoundingBoxAscent / displayScale,
            actualBoundingBoxDescent: measured.actualBoundingBoxDescent / displayScale};
          return {tempo, unit, symbols, ink};
        });
        const layout = glyph.doLayout;
        glyph.doLayout = function() {
          layout.call(this);
          this.height = Math.max(this.height, ...marks.map(m => m.ink.actualBoundingBoxAscent + m.ink.actualBoundingBoxDescent));
        };
        glyph.paint = function(x, y, canvas) {
          const old = canvas.textBaseline;
          canvas.textBaseline = alphaTab.platform.TextBaseline.Alphabetic;
          canvas.font = resources.elementFonts.get(alphaTab.NotationElement.EffectMarker);
          for (const {tempo, unit, symbols, ink} of marks) {
            let left = x + renderer.getRatioPositionX(tempo.ratioPosition) - ink.width / 2;
            const baseline = y + this.y + this.height - ink.actualBoundingBoxDescent;
            if (tempo.text) { canvas.fillText(tempo.text + ' ', left, baseline); left += canvas.measureText(tempo.text + ' ').width; }
            canvas.fillMusicFontSymbols(left, baseline, scale, symbols);
            canvas.fillText(` = ${unit.value}`, left + ink.width, baseline);
          }
          canvas.textBaseline = old;
        };
        return glyph;
      };
    }
  }

  function notationScore() {
    const score = new alphaTab.model.Score(), style = score.stylesheet;
    style.firstSystemTrackNameOrientation = style.otherSystemsTrackNameOrientation = alphaTab.model.TrackNameOrientation.Horizontal;
    style.firstSystemTrackNameMode = style.otherSystemsTrackNameMode = alphaTab.model.TrackNameMode.FullName;
    return score;
  }

  const compactScores = new WeakSet(), compactFactories = new WeakSet(), compactLayouts = new WeakSet();
  function registerCompactEngraving() {
    // TG 2.1.0 TGLayout.getDurationWidth / TGMeasureImpl.makeBeat: each onset
    // takes the smallest active voice's base width; dots and tuplets do not
    // change that width. TGNoteImpl's compact bends add zero effect width.
    // Keep alphaTab's complete bend/grace/text glyphs and their collision floor
    // instead of copying TG's reduced compact bend drawing.
    for (const factory of alphaTab.Environment.defaultRenderers) {
      if (compactFactories.has(factory)) continue;
      compactFactories.add(factory);
      const create = factory.create;
      factory.create = function(scoreRenderer, bar) {
        const renderer = create.call(this, scoreRenderer, bar), layout = renderer.doLayout;
        renderer.doLayout = function(...args) {
          const info = this.layoutingInfo;
          if (compactScores.has(bar.staff.track.score) && !compactLayouts.has(info)) {
            compactLayouts.add(info);
            const widths = new Map(), chords = new Set();
            for (const voice of bar.voices) for (const beat of voice.beats) {
              if (beat.graceType !== alphaTab.model.GraceType.None || beat.isEmpty) continue;
              const time = beat.absoluteDisplayStart;
              const width = [30, 25, 21, 20, 19, 18][Math.min(5, Math.max(0, Math.log2(beat.duration)))];
              widths.set(time, Math.min(widths.get(time) ?? Infinity, width));
              if (beat.hasChord && (beat.chord.showName || beat.chord.showDiagram)) chords.add(time);
            }
            const times = [...widths.keys()].sort((a, b) => a - b);
            for (let i = 1; i < times.length; i++) if (chords.has(times[i - 1]) && chords.has(times[i]))
              widths.set(times[i - 1], Math.max(widths.get(times[i - 1]), 13 + bar.staff.tuning.length * 5));
            const springs = () => [...info.springs.values()].sort((a, b) => a.timePosition - b.timePosition);
            const compact = () => {
              const sorted = springs();
              let width = 0;
              for (let i = 0; i < sorted.length; i++) {
                const spring = sorted[i];
                const space = Math.max(widths.get(spring.timePosition) ?? 18,
                  spring.postSpringWidth + (sorted[i + 1]?.preSpringWidth || 0));
                spring.springConstant = 1 / space;
                width += space;
              }
              info.totalSpringConstant = width ? 1 / width : -1;
              info.minStretchForce = width ? 1 : -1;
            };
            // Pinned alphaTab 1.8.4 RenderStaff assigns layoutingInfo before
            // doLayout. Preserve finish's grace rods and recompute's version/
            // minimum-duration bookkeeping when a later bar changes a system.
            for (const method of ['finish', 'recomputeSpringConstants']) {
              const original = info[method];
              info[method] = function(...args) { const result = original.apply(this, args); compact(); return result; };
            }
            // Public springs only: alphaTab's cached on-time positions would
            // otherwise retain Gourlay positions at an unchanged stretch force.
            info.buildOnTimePositions = function(force) {
              // Page justification can request slightly less than the minimum
              // stretch force. Keep the compact glyph collision floor intact.
              force = Math.max(info.minStretchForce, force);
              const sorted = springs(), positions = new Map();
              let x = sorted[0]?.preSpringWidth || 0;
              for (const spring of sorted) {
                positions.set(spring.timePosition, x);
                x += force / spring.springConstant;
              }
              return positions;
            };
          }
          return layout.apply(this, args);
        };
        return renderer;
      };
    }
  }

  function spaceChordDiagrams(api, score) {
    const resources = api.settings.display.resources, metrics = resources.engravingSettings;
    const measure = document.createElement('canvas').getContext('2d');
    measure.font = resources.elementFonts.get(alphaTab.NotationElement.ChordDiagrams).toCssString();
    let padding = 5; // alphaTab's default padding for a compact chord chart.
    for (const track of score.tracks) for (const staff of track.staves)
      for (const chord of staff.chords?.values() || []) {
        if (!chord.showName) continue;
        const text = measure.measureText(chord.name);
        const width = Math.max(text.width, text.actualBoundingBoxLeft + text.actualBoundingBoxRight);
        const grid = (chord.strings.length - 1) * metrics.chordDiagramStringSpacing;
        padding = Math.max(padding, (width - grid) / 2 + 5);
      }
    if (metrics.chordDiagramPaddingX !== padding) {
      metrics.chordDiagramPaddingX = padding;
      api.updateSettings();
    }
  }

  function notationTrack(score, id, spec, ranges, source, tieTargets, onBeat = () => {}, onNote = () => {}) {
    const m = alphaTab.model, t = new m.Track(), staff = new m.Staff();
    score.addTrack(t); t.name = spec.name || id; t.addStaff(staff);
    staff.stringTuning.tunings = [...spec.tuning]; staff.capo = spec.capo || 0;
    const drums = isPercussion(spec), drumBeats = new Map(), previousDrumNotes = new Map();
    if (drums) { staff.isPercussion = true; t.percussionArticulations = drumArticulations(); }
    if (spec.color) {
      t.color = new m.Color(...spec.color.match(/[0-9a-f]{2}/gi).map(h => parseInt(h, 16)));
      t.style = new m.ElementStyle(); t.style.colors.set(m.TrackSubElement.TrackName, t.color); t.style.colors.set(m.TrackSubElement.StringTuning, t.color);
    }
    const voices = [...new Set([0, ...source.map(b => b.voice)])].sort((a, b) => a - b);
    const strokeOwners = new Map(), chordOwners = new Map();
    for (const b of [...source].sort((a, b) => a.voice - b.voice)) {
      const key = [...rat(...b.at), b.cohort || 0].join('/'), previous = strokeOwners.get(key);
      if (!previous || !previous.notes.length && b.notes.length) strokeOwners.set(key, b);
      if (!chordOwners.has(key)) chordOwners.set(key, b);
    }
    const slideTargets = new Set(), hammerTargets = new Map();
    for (const v of voices) {
      const ordered = source.filter(b => b.voice === v).sort((a, b) => cmp(a.at, b.at));
      ordered.forEach((b, i) => {
        for (const n of b.notes) if (n.slide && n.string != null &&
          ordered[i + 1]?.notes.some(next => next.string === n.string)) slideTargets.add(n.id);
        for (const n of b.notes) if (n.hammer && n.string != null) {
          const target = ordered.slice(i + 1).find(next => next.notes.some(note => note.string === n.string));
          if (target) hammerTargets.set(n.id, target.at);
        }
      });
    }
    for (const range of ranges) {
      if (score.tracks.length === 1) {
        const master = new m.MasterBar(); master.timeSignatureNumerator = range.meter[0]; master.timeSignatureDenominator = range.meter[1];
        master.tripletFeel = !range.continuation && ({eighth: m.TripletFeel.Triplet8th, sixteenth: m.TripletFeel.Triplet16th}[range.swing]) || m.TripletFeel.NoTripletFeel;
        master.isRepeatStart = !!range.repeat_open && !range.continuation;
        master.isDoubleBar = !!range.double_bar && !range.continues;
        // Native/TG count is additional passes; alphaTab's count includes the first.
        master.repeatCount = range.repeat_close && !range.continues ? range.repeat_close + 1 : 0;
        master.alternateEndings = range.continuation ? 0 : (range.endings || []).reduce((mask, pass) => mask | (1 << (pass - 1)), 0);
        if (range.marker && !range.continuation) {
          master.section = new m.Section(); master.section.text = range.marker.title;
        }
        master.isAnacrusis = cmp(sub(range.to, range.from), rat(4 * range.meter[0], range.meter[1])) !== 0; score.addMasterBar(master);
      }
      const bar = new m.Bar(); staff.addBar(bar);
      const own = range.staff?.[id] || {}, clef = own.clef || spec.clef || 'treble', key = own.key || spec.key;   // a measure's clef/key change
      bar.clef = drums ? m.Clef.Neutral : {treble: m.Clef.G2, bass: m.Clef.F4, alto: m.Clef.C3, tenor: m.Clef.C4, percussion: m.Clef.Neutral}[clef];
      bar.keySignature = drums ? 0 : key?.fifths || 0; bar.keySignatureType = key?.mode === 'minor' ? m.KeySignatureType.Minor : m.KeySignatureType.Major;
      if (!range.authored || range.continuation) {
        bar.style = new m.ElementStyle();
        for (const element of [m.BarSubElement.StandardNotationTimeSignature, m.BarSubElement.GuitarTabsTimeSignature]) bar.style.colors.set(element, new m.Color(0, 0, 0, 0));
      }
      for (const v of voices) {
        const av = new m.Voice(); bar.addVoice(av); let cursor = range.from, previousWritten = null;
        function emit(length, original, continuation = false, preferred = null) {
          const values = original && cmp(length, duration(original.written)) === 0 ? [original.written] : spellSpan(length, preferred);
          values.forEach((w, index) => {
            const b = new m.Beat(); b.duration = w.value; b.dots = w.dots || 0;
            if (original?.text && cmp(cursor, original.at) === 0) b.text = original.text;
            if (original?.lyricLabel && !continuation && index === 0) b.lyrics = [original.lyricLabel];
            if (original?.chord && !continuation && index === 0 && chordOwners.get([...rat(...original.at), original.cohort || 0].join('/')) === original) {
              const chord = new m.Chord(), native = original.chord;
              chord.name = native.name; chord.firstFret = chordFirstFret(native); chord.strings = [...native.frets];
              chord.showName = !!native.name; chord.showDiagram = true; chord.showFingering = false;
              b.chordId = JSON.stringify([id, original.id, original.at, native]);
              staff.addChord(b.chordId, chord);
            }
            if (original && !continuation && index === 0 && strokeOwners.get([...rat(...original.at), original.cohort || 0].join('/')) === original) {
              if (original.stroke) {
                b.brushType = m.BrushType[original.stroke.direction === 'up' ? 'BrushUp' : 'BrushDown'];
              }
              if (original.pick_stroke) b.pickStroke = m.PickStroke[original.pick_stroke === 'up' ? 'Up' : 'Down'];
            }
            b.tupletNumerator = (w.tuplet || [1, 1])[0]; b.tupletDenominator = (w.tuplet || [1, 1])[1];
            const stem = original?.stem || spec.stem || 'auto';
            b.preferredBeamDirection = stem === 'auto' ? null : alphaTab.rendering.BeamDirection[stem === 'up' ? 'Up' : 'Down'];
            const curveFrom = original ? num(sub(cursor, original.at)) * 12 / num(duration(original.written)) : 0;
            const curveTo = original ? curveFrom + num(duration(w)) * 12 / num(duration(original.written)) : 12;
            const bars = original?.notes.filter(n => n.tremolo_bar != null) || [];
            if (bars.length) {
              if (bars.length === original.notes.length && bars.every(n => JSON.stringify(n.tremolo_bar) === JSON.stringify(bars[0].tremolo_bar))) {
                // TG bend values are quarter tones; tremolo-bar values are
                // semitones. alphaTab uses quarter tones and 0..60 positions.
                for (const point of engravingCurve(bars[0].tremolo_bar, curveFrom, curveTo, 2)) b.addWhammyBarPoint(point);
              } else b.text = [b.text, `Tremolo bar: ${bars.map(n => `string ${n.string ?? n.id}`).join(', ')} (individual curves)`].filter(Boolean).join(' · ');
            }
            if (original?.notes.some(n => n.velocity != null)) {
              const velocities = original.notes.map(n => n.velocity ?? null);
              // Engrave the nearest conventional dynamic for a uniform,
              // nonzero velocity. Exact and mixed values remain in the editor
              // and note tooltips; this projection never drives playback.
              b.dynamics = velocities[0] > 0 && velocities.every(value => value === velocities[0]) ?
                Math.max(0, Math.min(7, Math.round((velocities[0] - 15) / 16))) : null;
            }
            const picking = original?.notes.filter(n => n.tremolo_picking && !n.trill) || [];
            if (picking.length) {
              const value = picking[0].tremolo_picking.value, marks = Math.log2(value / b.duration);
              // alphaTab 1.8.4 stores tremolo strokes relative to this beat's
              // duration. Its legacy tremoloSpeed setter assumes a quarter.
              if (picking.length === original.notes.length &&
                  picking.every(n => n.tremolo_picking.value === value) &&
                  Number.isInteger(marks) && marks >= 1 && marks <= m.TremoloPickingEffect.maxMarks) {
                b.tremoloPicking = new m.TremoloPickingEffect(); b.tremoloPicking.marks = marks;
              } else b.text = [b.text, `Tremolo picking: ${picking.map(n =>
                `string ${n.string ?? n.id} 1/${n.tremolo_picking.value}`).join(', ')}`].filter(Boolean).join(' · ');
            }
            if (original && !continuation && index === 0) {
              const marks = tapSlapPop.map(([flag, label, field]) => ({label, field, notes: original.notes.filter(n => n[flag])}))
                .filter(mark => mark.notes.length);
              if (marks.length === 1 && marks[0].notes.length === original.notes.length) b[marks[0].field] = true;
              else if (marks.length) b.text = [b.text, ...marks.map(mark =>
                `${mark.label}: ${mark.notes.map(n => n.string != null ? `string ${n.string}` : `note ${n.id}`).join(', ')}`)]
                .filter(Boolean).join(' · ');
              const fades = original.notes.filter(n => n.fade_in);
              if (fades.length) {
                // alphaTab exposes fade on the whole beat. Keep sparse native
                // note flags exact with text instead of marking the whole chord.
                if (fades.length === original.notes.length) b.fade = m.FadeType.FadeIn;
                else b.text = [b.text, `Fade-in: ${fades.map(n => `string ${n.string ?? n.id}`).join(', ')}`]
                  .filter(Boolean).join(' · ');
              }
              const graces = original.notes.filter(n => n.grace);
              if (graces.length) {
                // alphaTab normalizes grace durations in finish(). Preserve the
                // exact parameters in the editor/tooltips, not duplicate score text.
                // Mixed timing cannot share a grace beat without inventing alignment.
                if (graces.every(n => n.string != null && !!n.grace.on_beat === !!graces[0].grace.on_beat)) {
                  const g = new m.Beat(); g.duration = graces[0].grace.value; g.dynamics = null;
                  g.graceType = graces[0].grace.on_beat ? m.GraceType.OnBeat : m.GraceType.BeforeBeat;
                  av.addBeat(g); onBeat(g, original, cursor, cursor, v);
                  for (const note of graces) {
                    const n = new m.Note();
                    if (drums) n.percussionArticulation = note.grace.fret;
                    else { n.string = spec.tuning.length + 1 - note.string; n.fret = note.grace.fret; }
                    n.isDead = !!note.grace.dead; g.addNote(n);
                    onNote(n, note, original, v); // Select the written main note, never a new edit identity.
                  }
                } else b.text = [b.text, graces.some(n => n.string == null) ? 'Grace (unassigned string)' :
                  'Grace (mixed timing)'].filter(Boolean).join(' · ');
              }
            }
            if (drums) {
              const key = cursor.join('/'), cohort = drumBeats.get(key) || {at: cursor, beats: []};
              drumBeats.set(key, cohort); cohort.beats.push(b);
            }
            av.addBeat(b); onBeat(b, original, cursor, add(cursor, duration(w)), v); cursor = add(cursor, duration(w));
            for (const note of original?.notes || []) {
              const n = new m.Note();
              if (drums) n.percussionArticulation = note.pitch;
              else if (Number.isInteger(note.string) && note.string >= 1 && note.string <= spec.tuning.length && Number.isInteger(note.fret)) {
                n.string = spec.tuning.length + 1 - note.string; n.fret = note.fret;
              } else { n.octave = Math.floor(note.pitch / 12); n.tone = note.pitch % 12; }
              n.accidentalMode = accidentalMode(note.spelling);
              n.isStaccato = !!note.staccato; n.isPalmMute = !!note.palm_mute; n.isDead = !!note.dead;
              n.isLetRing = !!note.let_ring;
              n.isGhost = !!note.ghost;
              n.accentuated = note.heavy_accent ? m.AccentuationType.Heavy : note.accent ? m.AccentuationType.Normal : m.AccentuationType.None;
              n.vibrato = note.vibrato ? m.VibratoType.Slight : m.VibratoType.None;
              if (note.harmonic) {
                const touches = [12, 9, 5, 7, 4, 3], kind = note.harmonic.type;
                const touch = kind === 'natural' ? touches.find(f => note.fret != null && f % 12 === note.fret % 12) : touches[note.harmonic.data ?? 0];
                if (touch != null && n.isStringed) {
                  n.harmonicType = m.HarmonicType[{natural:'Natural', artificial:'Artificial', tapped:'Tap', pinch:'Pinch', semi:'Semi'}[kind]];
                  n.harmonicValue = touch;
                  if (kind === 'natural' && note.pitch - note.fret + n.harmonicPitch < 0) {
                    n.harmonicType = m.HarmonicType.None;
                    b.text = [b.text, 'Natural harmonic (primary clamped to pitch 0)'].filter(Boolean).join(' · ');
                  }
                } else b.text = [b.text, `${kind} harmonic: string ${note.string ?? note.id} (written pitch retained)`].filter(Boolean).join(' · ');
              }
              for (const point of engravingCurve(note.bend, curveFrom, curveTo)) n.addBendPoint(point);
              if (note.slide && Math.abs(curveTo - 12) < 1e-9) {
                if (slideTargets.has(note.id)) n.slideOutType = m.SlideOutType.Shift;
                else b.text = [b.text, `Slide: string ${note.string ?? note.id} (no following note)`].filter(Boolean).join(' · ');
              }
              if (note.hammer && Math.abs(curveTo - 12) < 1e-9) {
                const target = hammerTargets.get(note.id);
                const targetBar = target ? ranges.findIndex(r => cmp(target, r.from) >= 0 && cmp(target, r.to) < 0) : -1;
                // alphaTab 1.8.4 searches this voice/string across rests, up to
                // three bars ahead. Never draw a link to an invented target.
                if (targetBar >= 0 && targetBar - ranges.indexOf(range) <= 3) n.isHammerPullOrigin = true;
                else b.text = [b.text, `Hammer-on/pull-off: string ${note.string ?? note.id}`].filter(Boolean).join(' · ');
              }
              n.isTieDestination = continuation || index > 0 || tieTargets.has(note.id); b.addNote(n);
              if (drums) {
                const lane = `${v}/${note.string}`, previous = previousDrumNotes.get(lane);
                // Explicit lane binding also survives the closed-hat display variant.
                if (n.isTieDestination) {
                  n.tieOrigin = previous?.key === note.pitch ? previous.note : null;
                  n.isTieDestination = !!n.tieOrigin;
                }
                previousDrumNotes.set(lane, {key: note.pitch, note: n});
              }
              if (note.trill) {
                if (n.isStringed) {
                  n.trillValue = n.stringTuning + note.trill.fret;
                  n.trillSpeed = note.trill.value;
                } else b.text = [b.text, `Trill: fret ${note.trill.fret}, 1/${note.trill.value}`].filter(Boolean).join(' · ');
              }
              onNote(n, note, original, v);
            }
          });
        }
        for (const b of source.filter(b => b.voice === v).sort((a, b) => cmp(a.at, b.at))) {
          const finish = add(b.at, duration(b.written)); if (cmp(finish, range.from) <= 0 || cmp(b.at, range.to) >= 0) continue;
          const start = cmp(b.at, range.from) < 0 ? range.from : b.at, stop = cmp(finish, range.to) > 0 ? range.to : finish;
          if (cmp(start, cursor) < 0) throw new Error('Overlapping beats in one voice need a separate voice.');
          if (cmp(start, cursor) > 0) emit(sub(start, cursor), null, false, previousWritten || b.written);
          emit(sub(stop, start), b, cmp(b.at, range.from) < 0); cursor = stop; previousWritten = b.written;
        }
        if (cmp(cursor, range.to) < 0) emit(sub(range.to, cursor), null, false, previousWritten);
      }
    }
    const drumCohorts = [...drumBeats.values()].sort((a,b) => cmp(a.at,b.at));
    // A cropped print still consults the preceding source beat (or gap).
    const prior = drumCohorts.length ? source.flatMap(b => [b.at, add(b.at, duration(b.written))])
      .filter(at => cmp(at, drumCohorts[0].at) < 0).sort(cmp).at(-1) : null;
    let previousKeys = new Set(prior ? source.filter(b => cmp(b.at, prior) === 0).flatMap(b => b.notes.map(n => n.pitch)) : []);
    for (const cohort of drumCohorts) {
      const notes = cohort.beats.flatMap(b => b.notes), keys = new Set(notes.map(n => n.percussionArticulation));
      for (const n of notes) if (n.percussionArticulation === 42 && !previousKeys.has(42)) n.percussionArticulation = 101;
      previousKeys = keys;
    }
    return t;
  }

  const lyricWidths = new WeakMap();
  const annotationWidths = new WeakMap();
  const annotationEffects = new WeakSet();
  function textLayoutError(api) {
    for (const track of api.score.tracks) for (const staff of track.staves) {
      const rows = new Map();
      for (const bar of staff.bars) for (const beat of bar.voices.flatMap(v => v.beats)
        .filter(b => b.lyrics).sort((a, b) => a.absoluteDisplayStart - b.absoluteDisplayStart)) {
        const ink = lyricWidths.get(beat), scale = api.settings.display.scale;
        const bounds = ink && api.boundsLookup?.findBeat(beat);
        if (!bounds) continue;
        const band = ink.renderer.topEffects.getBand(beat.voice, ink.effectId);
        const y = Math.round((bounds.barBounds.realBounds.y + (band?.y || 0) * scale) * 10);
        const left = bounds.onNotesX - (ink.left + ink.space / 2) * scale;
        if (rows.has(y) && left < rows.get(y) - .1)
          return `Lyrics in bar ${bar.index + 1} need more width. Widen the score view or reduce print scale/use wider paper.`;
        rows.set(y, bounds.onNotesX + (ink.right + ink.space / 2) * scale);
      }
      const labels = new Map();
      for (const bar of staff.bars) for (const beat of bar.voices.flatMap(v => v.beats)
        .sort((a, b) => a.absoluteDisplayStart - b.absoluteDisplayStart)) {
        const bounds = api.boundsLookup?.findBeat(beat), scale = api.settings.display.scale;
        if (!bounds) continue;
        for (const ink of annotationWidths.get(beat)?.values() || []) {
          const band = ink.renderer.topEffects.getBand(beat.voice, ink.effectId);
          const y = Math.round((bounds.barBounds.realBounds.y + (band?.y || 0) * scale) * 10);
          const left = bounds.onNotesX - ink.left * scale;
          if (labels.has(y) && left < labels.get(y) - .1)
            return `${ink.label} in bar ${bar.index + 1} need more width. Widen the score view or reduce print scale/use wider paper.`;
          labels.set(y, bounds.onNotesX + ink.right * scale);
        }
      }
    }
    return '';
  }
  function registerLyricsEngraving() {
    registerTempoEngraving();
    // alphaTab 1.8.4 registers lyrics on the TAB renderer only. Share its
    // existing glyph with the global text effects so staff-only/one-string
    // views also draw the explicit backend anchors, without re-tokenizing.
    const renderers = alphaTab.Environment.defaultRenderers;
    // These native labels otherwise share endpoint slots. Their different text
    // baselines also need the display effect-band padding used by both views.
    for (const renderer of renderers) for (const band of renderer.effectBands)
      if ([alphaTab.NotationElement.EffectMarker, alphaTab.NotationElement.EffectTap,
        alphaTab.NotationElement.EffectHarmonics].includes(band.effect.notationElement)
          && band.effect.canShareBand)
        Object.defineProperty(band.effect, 'canShareBand', {value: false});
    // Authored beat text and chord names need horizontal room too. alphaTab's
    // text glyph measures its ink, but its effect band only reserves height.
    // Use the same note springs as lyrics so editing and print wrap together.
    for (const renderer of renderers) for (const band of renderer.effectBands) {
      const element = band.effect.notationElement;
      const chord = element === alphaTab.NotationElement.EffectChordNames;
      if ((!chord && (element !== alphaTab.NotationElement.EffectText || band.effect.sizingMode !== 1))
          || annotationEffects.has(band.effect)) continue;
      annotationEffects.add(band.effect);
      const create = band.effect.createNewGlyph;
      band.effect.createNewGlyph = function(renderer, beat) {
        const glyph = create.call(this, renderer, beat), layout = glyph.doLayout, effectId = this.effectId;
        glyph.doLayout = function() {
          layout.call(this);
          const canvas = renderer.scoreRenderer.canvas;
          canvas.font = this.font;
          const width = this.width + canvas.measureText(' ').width;
          if (!annotationWidths.has(beat)) annotationWidths.set(beat, new Map());
          annotationWidths.get(beat).set(effectId, {renderer, effectId,
            label: chord ? 'Chord names' : 'Beat annotations',
            left: chord ? width / 2 : 0, right: chord ? width / 2 : width});
          renderer.layoutingInfo.addSpring(beat.absoluteDisplayStart, beat.displayDuration, 0,
            chord ? width / 2 : 0, chord ? width / 2 : width);
        };
        return glyph;
      };
    }
    const tab = renderers.find(r => r.staffId === 'tab'), shared = renderers.find(r => r.staffId === 'slash');
    const index = tab.effectBands.findIndex(b => b.effect.notationElement === alphaTab.NotationElement.EffectLyrics);
    if (index >= 0) {
      const [band] = tab.effectBands.splice(index, 1), create = band.effect.createNewGlyph;
      const measure = document.createElement('canvas').getContext('2d');
      measure.textAlign = 'center';
      // The native lyric glyph reserves height only. Add its centered text to
      // the same springs as the notes, before native spacing/wrapping finishes.
      band.effect.createNewGlyph = function(renderer, beat) {
        const glyph = create.call(this, renderer, beat), layout = glyph.doLayout, effectId = this.effectId;
        glyph.doLayout = function() {
          layout.call(this);
          const canvas = renderer.scoreRenderer.canvas;
          canvas.font = this.font;
          // SVG's alphaTab canvas estimates character widths. Browser metrics at
          // the actual scale also cover italic overhang and small-font rounding.
          const scale = renderer.settings.display.scale;
          measure.font = this.font.toCssString(scale);
          const ink = {left: 0, right: 0, space: measure.measureText(' ').width / scale, renderer, effectId};
          let half = 0;
          for (const line of beat.lyrics) {
            const bounds = measure.measureText(line);
            ink.left = Math.max(ink.left, bounds.width / (2 * scale), bounds.actualBoundingBoxLeft / scale);
            ink.right = Math.max(ink.right, bounds.width / (2 * scale), bounds.actualBoundingBoxRight / scale);
            half = Math.max(half, canvas.measureText(line).width / 2);
          }
          half = Math.max(half, ink.left, ink.right) + Math.max(canvas.measureText(' ').width, ink.space) / 2;
          lyricWidths.set(beat, ink);
          renderer.layoutingInfo.addSpring(beat.absoluteDisplayStart, beat.displayDuration, 0, half, half);
        };
        return glyph;
      };
      shared.effectBands.push(band);
    }
  }
  function mount(root, host) {
    registerLyricsEngraving();
    registerCompactEngraving();
    let view = null, clock = null, playbackClockPlan = null, playbackClock = null, track = '', voice = 0, at = [0, 1], string = 1, chosen = null;
    let written = {value: 4, dots: 0, tuplet: [1, 1]}, pending = '', busy = false, destroyed = false;
    let freeRequested = false;
    let lastDigit = null, fretChain = Promise.resolve(), saving = Promise.resolve();
    let fretJob = null, fretContext = '', fretEpoch = 0;
    let clipboard = null, clipboardSong = null, copying = null, selectedBeats = new Set(), selectedNotes = new Map(), curveTarget = null, chordTarget = null, chordEntryVelocity = 95;
    let rangeSelection = [];
    const crossRange = () => rangeSelection.length > 1 || rangeSelection.some(g => g.occurrence !== occurrence());
    const noteRange = () => crossRange() || selectedBeats.size > 1;
    const selectedGroups = () => rangeSelection.length ? rangeSelection : [{occurrence: occurrence(), beats: [...selectedBeats]}];
    let chordLibrary = null, libraryBusy = false;
    let chordRecognition = null, recognitionToken = 0;
    let chordGeneration = null, generationToken = 0;
    let lyricsTarget = null;
    let navigationEcho = null;
    let api = null, renderKey = '', refs = new Map(), beatRefs = new Map(), playhead = null, notifying = false, rawSelected = null, ambiguousSelection = false;
    let renderedBeats = [], tabHits = [], staffHits = [], revealCaret = false;
    const scoreCursor = text('div', '', 'vt-tab-playhead'); scoreCursor.hidden = true; scoreCursor.setAttribute('aria-hidden', 'true');
    const editCaret = text('div', '', 'vt-tab-edit-caret'); editCaret.hidden = true; editCaret.setAttribute('aria-hidden', 'true');
    const abort = new AbortController(), listen = (el, type, fn, options = {}) => el.addEventListener(type, fn, {...options, signal: abort.signal});
    root.classList.add('vt-tab'); root.tabIndex = 0; root.setAttribute('aria-label', 'Tablature editor');
    root.innerHTML = `<div class="vt-tab-tools">
      <label>Track <select data-ui="track"></select></label><label>Voice <select data-ui="voice"><option value="0">1</option><option value="1">2</option></select></label>
      <label data-ui="lane-label" hidden>Lane <select data-ui="lane" aria-label="Drum lane"></select></label>
      <button type="button" data-action="setup" title="Tuning, capo, strings, maximum fret, clef, key and MIDI program">Track setup (tuning, capo)</button><button type="button" data-action="lyrics">Lyrics</button><button type="button" data-action="new-track">New track</button>
      <label title="Scroll the full score to the sounding measure while not editing. Selecting notes or browsing pauses follow; check again to resume."><input type="checkbox" data-ui="follow" checked> Follow playback</label><label title="With editing on, a click on the staff adds the clicked pitch there or removes it (TuxGuitar's edition mouse mode); natural follows the key signature, sharps/flats alters the unaltered steps">Staff click <select data-ui="staff-mode"><option value="natural" selected>enters notes</option><option value="altered">enters sharps/flats</option><option value="select">selects</option></select></label><span data-ui="order-context"></span>
      <button type="button" data-action="measures">Measures</button><button type="button" data-action="transpose">Transpose…</button><button type="button" data-action="properties">Song properties</button><button type="button" data-action="rehearsal">Rehearse selection</button><button type="button" data-action="print">Print preview</button>
      <label>Duration <select data-ui="duration"><option value="1">Whole</option><option value="2">Half</option><option value="4" selected>Quarter</option><option value="8">Eighth</option><option value="16">16th</option><option value="32">32nd</option><option value="64">64th</option></select></label>
      <label>Dots <select data-ui="dots"><option>0</option><option>1</option><option>2</option></select></label>
      <label>Tuplet <input data-ui="tuple-n" type="number" min="1" max="32" value="1" aria-label="Tuplet notes">:<input data-ui="tuple-d" type="number" min="1" max="32" value="1" aria-label="Tuplet time"></label>
      <button type="button" data-action="duration">Apply duration</button><button type="button" data-action="longer" title="+">Longer +</button><button type="button" data-action="shorter" title="−">Shorter −</button><button type="button" data-action="rest">Rest</button>
      <small data-ui="range-duration" hidden></small>
      <label title="Move or resize following notes and adjust rests within the measure, retaining expression on intact notes. Insufficient room keeps a local beat’s previous duration; a cross-measure duration edit refuses as a whole. Protected notation or consuming a selected rest may refuse."><input type="checkbox" data-ui="fit">Fit within measure</label><label title="Free duration takes precedence over Fit and repacks both voices' beat groups, including rests. Matrix entry keeps its original anchor and refuses sounding overlaps. Duration changes and Insert rest may extend the bar; later bars wait for it. Repair with Measures. Enable Independent measures for reused or divided patterns."><input type="checkbox" data-ui="free-edit">Free edit</label><span data-ui="free-required" hidden>Required: this bar ends early or is overfull.</span>
      <label>Beam group stem <select data-ui="beat-stem"><option value="inherit">Track default</option><option value="auto">Auto</option><option value="up">Up</option><option value="down">Down</option></select></label><button type="button" data-action="beat-stem" title="Apply to the caret voice's beam group; Ctrl+Up/Down sets its direction">Apply stem</button>
      <label>Beat stroke <select data-ui="stroke-direction" aria-label="Beat stroke direction"><option value="">None</option><option value="up">Up · high string first</option><option value="down">Down · low string first</option></select></label>
      <label>Stroke value <select data-ui="stroke-value" aria-label="Stroke duration value"><option value="4">1/4</option><option value="8">1/8</option><option value="16" selected>1/16</option><option value="32">1/32</option><option value="64">1/64</option></select></label>
      <button type="button" data-action="stroke" title="Apply to both voices of this track at this written onset. None clears the stroke.">Apply stroke</button>
      <label>Pick direction <select data-ui="pick-stroke" aria-label="Pick stroke direction"><option value="">None</option><option value="up">Up</option><option value="down">Down</option></select></label>
      <button type="button" data-action="pick-stroke" title="Notation only, shared by both voices at this onset. None clears it. This does not repeat notes.">Apply pick direction</button>
      <button type="button" data-action="tie" title="L: tie the selected note to its preceding contiguous note">Tie</button>
      <label>Dynamics <select data-ui="dynamics" aria-label="Dynamics"><option value="">Instrument default</option><option value="15">ppp</option><option value="31">pp</option><option value="47">p</option><option value="63">mp</option><option value="79">mf</option><option value="95">f</option><option value="111">ff</option><option value="127">fff</option><option value="custom">Custom / mixed</option></select></label>
      <label>Velocity <input data-ui="velocity" type="number" min="0" max="127" aria-label="MIDI velocity" placeholder="inherit"></label><button type="button" data-action="velocity">Apply velocity</button>
      <small data-ui="velocity-info"></small>
      <label data-ui="range-expression" hidden>Range articulation <select data-ui="range-articulation" aria-label="Range articulation action"><option value="set">Set on selected voice</option><option value="clear">Clear from selected voice</option></select></label>
      <small data-ui="range-expression-info" hidden></small>
      <button type="button" data-action="staccato" aria-pressed="false" title="Toggle staccato on the selected note or chord">Staccato</button>
      <button type="button" data-action="palm-mute" aria-pressed="false" title="Toggle palm mute on the selected note or chord">Palm mute</button>
      <button type="button" data-action="let-ring" aria-pressed="false" title="Let the selected note or chord sustain beyond its written duration; replaces palm mute and staccato">Let ring</button>
      <button type="button" data-action="fade-in" aria-pressed="false" title="Toggle fade-in on the selected notes. Expression affects the whole logical track, including other sounding notes and release tails.">Fade-in</button>
      <span class="vt-tab-help">Fade-in affects the whole track in playback and exports. Standalone IT reports its bounded row/volume approximation.</span>
      <label>Tap / slap / pop <select data-ui="tap-slap-pop" aria-label="Tap, slap or pop marking"><option value="">None</option><option value="tapping">Tap</option><option value="slapping">Slap</option><option value="popping">Pop</option><option value="mixed" disabled>Mixed</option></select></label>
      <button type="button" data-action="tap-slap-pop">Apply marking</button>
      <span class="vt-tab-help">Tap/slap/pop are notation markings; native playback and MIDI stay unchanged. Tapped harmonic is separate.</span>
      <button type="button" data-action="dead" aria-pressed="false" title="Toggle dead note on the selected note or chord; written pitch and fret are retained">Dead note</button>
      <button type="button" data-action="vibrato" aria-pressed="false" title="Toggle vibrato on the selected note or chord">Vibrato</button>
      <button type="button" data-action="slide" aria-pressed="false" title="Slide to the next authored beat on the same string; the destination is retriggered">Slide</button>
      <button type="button" data-action="bend" title="Edit bend points for the selected note or chord">Bend…</button>
      <button type="button" data-action="tremolo-bar" title="Edit tremolo-bar points for the selected note or chord">Tremolo bar…</button>
      <button type="button" data-action="ghost" aria-pressed="false">Ghost</button>
      <button type="button" data-action="accent" aria-pressed="false">Accent</button>
      <button type="button" data-action="heavy-accent" aria-pressed="false">Heavy accent</button>
      <button type="button" data-action="hammer" aria-pressed="false">Hammer-on/pull-off</button>
      <label>Harmonic <select data-ui="harmonic-type" aria-label="Harmonic type"><option value="">None</option><option value="natural">Natural</option><option value="artificial">Artificial</option><option value="tapped">Tapped</option><option value="pinch">Pinch</option><option value="semi">Semi</option><option value="mixed" disabled>Mixed</option></select></label>
      <label>Touch <select data-ui="harmonic-data" aria-label="Harmonic touch"><option value="0">12 (+12)</option><option value="1">9 (+28)</option><option value="2">5 (+24)</option><option value="3">7 (+19)</option><option value="4">4 (+28)</option><option value="5">3 (+31)</option></select></label>
      <button type="button" data-action="harmonic">Apply harmonic</button>
      <label>Repetition <select data-ui="repetition-type" aria-label="Note repetition"><option value="">None</option><option value="trill">Trill</option><option value="tremolo_picking">Tremolo picking</option><option value="mixed" disabled>Mixed</option></select></label>
      <label>Alternate fret <input data-ui="trill-fret" type="number" min="0" max="36" step="1" aria-label="Trill alternate fret" title="Absolute fret on each selected note’s resolved string"></label>
      <label>Rate <select data-ui="repetition-value" aria-label="Repetition rate"></select></label>
      <button type="button" data-action="repetition">Apply repetition</button>
      <span title="Trill and tremolo picking need explicit velocity. They replace bend, tremolo bar, slide, hammer, dead note and vibrato. A written harmonic stays, but repetition plays ordinary pitches.">Trill / picking replaces pitch effects</span>
      <label>Grace <select data-ui="grace-kind" aria-label="Grace note"><option value="">None</option><option value="grace">Grace note</option><option value="mixed" disabled>Mixed</option></select></label>
      <label><span data-ui="grace-key-label">Grace fret</span> <input data-ui="grace-fret" type="number" min="0" max="36" step="1" aria-label="Grace absolute fret"></label>
      <label>Grace value <select data-ui="grace-value"><option value="16">1/16</option><option value="32">1/32</option><option value="64">1/64</option></select></label>
      <label>Grace velocity <input data-ui="grace-velocity" type="number" min="0" max="127" step="1" aria-label="Grace velocity"></label>
      <label>Grace timing <select data-ui="grace-timing"><option value="before">Before beat</option><option value="on">On beat</option></select></label>
      <label>Grace transition <select data-ui="grace-transition" title="Notation only; does not add a slide, bend or hammer to playback"><option value="none">None</option><option value="slide">Slide (notation only)</option><option value="bend">Bend (notation only)</option><option value="hammer">Hammer (notation only)</option></select></label>
      <label><input data-ui="grace-dead" type="checkbox">Dead grace</label><button type="button" data-action="grace">Apply grace</button>
      <button type="button" data-action="delete">Delete note</button><button type="button" data-action="delete-beat">Delete beat</button><button type="button" data-action="insert-rest" title="Ins: a rest at the caret; later beats of this voice move right inside the measure">Insert rest</button><button type="button" data-action="move-beats-left" title="TuxGuitar's Beat &gt; Move beats left: this track's beats from the caret to the end move left by the caret beat; the caret beat goes">◀ Move beats</button><button type="button" data-action="move-beats-right" title="TuxGuitar's Beat &gt; Move beats right: this track's beats from the caret to the end move right by the caret beat">Move beats ▶</button><button type="button" data-action="clean-beat" title="Make both voices at the selected beats rests and clear their text, chord and strokes">Clean beat</button><button type="button" data-action="remove-unused-voice" title="Remove the rests of a voice that is unused at the selected beats, in their measures">Remove unused voice</button>
      <label>Move amount <input data-ui="move-amount" placeholder="caret" aria-label="Move amount in quarter notes, blank uses caret duration" style="width:4em"> quarter notes</label>
      <button type="button" data-action="undo">Undo</button><button type="button" data-action="redo">Redo</button>
      <button type="button" data-action="play">Play here</button>
    </div>
    <div class="vt-tab-nav">
      <div role="group" aria-label="Track navigation">Track
        <button type="button" data-action="track-first">First track</button><button type="button" data-action="track-previous" title="Ctrl+Shift+Up">Previous track</button>
        <button type="button" data-action="track-next" title="Ctrl+Shift+Down">Next track</button><button type="button" data-action="track-last">Last track</button>
      </div>
      <div role="group" aria-label="Measure navigation">Measure
        <button type="button" data-action="measure-first" title="Ctrl+Shift+Left">First measure</button><button type="button" data-action="measure-previous" title="Ctrl+Left">Previous measure</button>
        <button type="button" data-action="measure-next" title="Ctrl+Right">Next measure</button><button type="button" data-action="measure-last" title="Ctrl+Shift+Right">Last measure</button>
      </div>
      <div role="group" aria-label="Marker navigation">
        <button type="button" data-action="marker-previous">Previous marker</button>
        <button type="button" data-action="marker-next">Next marker</button>
        <span data-ui="markers"></span>
      </div>
    </div>
    <form class="vt-tab-panel" data-panel="properties" aria-label="Song properties" hidden>
      <strong>Song properties</strong><button type="button" data-action="close-properties">✕ Close</button>
      <p>Saved with the score. The tracker module keeps its short title.</p>
      ${['title','artist','album','author','date','copyright','writer','transcriber'].map(key => `<label>${key[0].toUpperCase()+key.slice(1)} <input data-credit="${key}" maxlength="200"></label>`).join('')}
      <label>Comments <textarea data-credit="comments" maxlength="8000" rows="3"></textarea></label>
      <button type="submit">Apply properties</button>
      <label>Template name <input data-ui="template-name" maxlength="80"></label><button type="button" data-action="save-template">Save setup template</button>
      <p>Templates retain band setup and credits, with new placeholder sounds and empty bars.</p>
    </form>
    <form class="vt-tab-setup vt-tab-panel" data-panel="setup" aria-label="Track setup" hidden>
      <label>Track ID <input data-ui="name" value="guitar" required></label>
      <label>Track kind <select data-ui="track-kind"><option value="pitched">Pitched strings</option><option value="percussion">Percussion lanes</option></select></label>
      <label>Display name <input data-ui="display-name" value="" maxlength="80"></label>
      <label>Color <input data-ui="color" type="color" value="#222222"></label>
      <label>Clef <select data-ui="clef"><option value="treble">Treble</option><option value="bass">Bass</option><option value="alto">Alto</option><option value="tenor">Tenor</option><option value="percussion">Percussion</option></select></label>
      <label>Key fifths (−7 flats … +7 sharps) <input data-ui="key-fifths" type="number" min="-7" max="7" value="0"></label>
      <label>Key mode <select data-ui="key-mode"><option value="major">Major</option><option value="minor">Minor</option></select></label>
      <label>Track stems <select data-ui="track-stem"><option value="auto">Auto</option><option value="up">Up</option><option value="down">Down</option></select></label>
      <label title="Note names, top string first: E4 B3 G3 D3 A2 E2 is standard guitar (MIDI numbers also work)">Tuning, top string first <input data-ui="tuning" value="E4 B3 G3 D3 A2 E2" required></label><label>Preset <select data-ui="tuning-preset"><option value="">choose…</option><option value="64,59,55,50,45,40">Standard (E A D G B E)</option><option value="64,59,55,50,45,38">Drop D</option><option value="63,58,54,49,44,39">Half step down (Eb)</option><option value="62,57,53,48,43,38">Whole step down (D)</option><option value="62,57,55,50,45,38">DADGAD</option><option value="62,59,55,50,43,38">Open G</option><option value="62,57,54,50,45,38">Open D</option><option value="64,59,55,50,45,40,35">7-string standard</option><option value="43,38,33,28">Bass 4-string</option><option value="43,38,33,28,23">Bass 5-string</option></select></label>
      <label title="Keep existing string channels, add new channels for extra strings, and retain raw Pattern data when strings are removed"><input data-ui="auto-channels" type="checkbox" checked> Assign channels automatically</label>
      <label>Channels (1-based, one per string) <input data-ui="channels" value="1,2,3,4,5,6" required disabled></label>
      <label>Instrument <input data-ui="instrument" type="number" min="1" value="1" required></label>
      <label>MIDI export program (0–127) <input data-ui="midi-program" type="number" min="0" max="127" step="1" placeholder="Unspecified"></label>
      <label>MIDI export bank (0–16383) <input data-ui="midi-bank" type="number" min="0" max="16383" step="1" placeholder="0"></label>
      <label>Capo <input data-ui="capo" type="number" min="-24" max="24" value="0" required></label>
      <label>Maximum fret <input data-ui="max-fret" type="number" min="0" max="36" value="29" required></label><label title="When tuning, capo, strings or maximum fret change: keep each note's pitch (TuxGuitar) or its string and fret">Retune keeps <select data-ui="retune-keep"><option value="pitch" selected>pitches</option><option value="frets">frets</option></select></label>
      <button type="submit">Apply track</button><button type="button" data-action="close-setup">Cancel</button>
      <div><button type="button" data-action="clone-track">Duplicate track</button><button type="button" data-action="track-up">Move track up</button><button type="button" data-action="track-down">Move track down</button></div>
      <div><label>My tuning <select data-ui="custom-tuning"><option value="">choose…</option></select></label><label>Name <input data-ui="tuning-name" maxlength="80"></label><button type="button" data-action="save-tuning">Save tuning</button><button type="button" data-action="delete-tuning">Delete saved tuning</button></div>
      <label><input type="checkbox" data-ui="remove-notes">Delete all this track’s authored beats, rests and incident ties</label><button type="button" data-action="delete-track">Delete track</button>
      <p>Choose existing channels explicitly. The song validates this mapping before changing any notes.</p>
      <p>Clef, key, color and stems affect notation only. Track deletion preserves raw Pattern data, channels, samples and measures.</p>
      <p>MIDI assignments describe the exported file; playback here uses the current samples. Blank program removes the assignment. Blank bank uses bank 0.</p>
      <p data-ui="midi-source-pan"></p>
    </form>
    <form class="vt-tab-setup vt-tab-lyrics vt-tab-panel" data-panel="lyrics" hidden novalidate aria-label="Track lyrics editor">
      <strong data-ui="lyrics-target"></strong>
      <label>Starting written measure <input data-ui="lyrics-from" aria-label="Lyrics starting written measure" type="number" min="1" max="2147483647" step="1" value="1"></label>
      <label style="flex-basis:100%">Lyrics <textarea data-ui="lyrics-text" aria-label="Raw track lyrics" rows="6" style="font:inherit;width:min(760px,100%);max-width:100%"></textarea></label>
      <p>One stream per track. Words follow authored written measures and reflow when notes or the arrangement change. Reused occurrences can have different words; playback repeats do not consume new words. A start beyond the last measure stays dormant.</p>
      <p>Unedited text keeps its original line endings. Editing this text saves line breaks as LF. Empty text keeps the starting measure; Remove lyrics deletes the stream. Save and Remove require stopped playback.</p>
      <p data-ui="lyrics-map" role="status"></p>
      <button type="submit" data-ui="lyrics-apply">Apply lyrics</button>
      <button type="button" data-action="lyrics-remove">Remove lyrics</button>
      <button type="button" data-action="lyrics-close">Cancel</button>
      <p data-ui="lyrics-status" role="status" aria-live="polite"></p>
    </form>
    <form class="vt-tab-setup vt-tab-chord vt-tab-panel" data-panel="chord" hidden novalidate aria-label="Chord diagram editor">
      <strong>Chord diagram</strong>
      <label>Name <input data-ui="chord-name" aria-label="Chord diagram name" maxlength="8192"></label>
      <label>First fret <input data-ui="chord-first" aria-label="Chord diagram first fret" type="number" min="0" step="1" value="0"></label>
      <p>Shared by both voices of this track at this onset. Apply annotation and Remove change only the diagram. An all-X diagram remains a literal muted diagram.</p>
      <p>Enter X for muted, 0 for open, or an absolute fret. First fret 0 keeps automatic positioning. Positive frets must fit within five frets. String 1 is on the right.</p>
      <div data-ui="chord-strings" style="display:flex;gap:8px;flex-wrap:wrap"></div>
      <svg data-ui="chord-preview" role="img" aria-label="Chord diagram preview, string 1 on the right" style="height:180px;max-width:100%;color:var(--hi,#dde8e5)"></svg>
      <button type="submit">Apply annotation</button><button type="button" data-action="remove-chord-diagram">Remove</button>
      <button type="button" data-action="close-chord-diagram">Cancel</button>
      <p data-ui="chord-status" role="status" aria-live="polite"></p>
      <div style="flex-basis:100%">
        <label>Name spelling <select data-ui="recognition-spelling" aria-label="Recognized chord name spelling"><option value="sharp">Sharps</option><option value="flat">Flats</option></select></label>
        <button type="button" data-action="chord-recognize">Recognize names</button>
        <label>Proposed name <select data-ui="recognized-name" aria-label="Recognized chord name"><option value="">Recognize names first</option></select></label>
        <button type="button" data-action="recognition-apply" disabled>Apply selected name</button>
        <p data-ui="recognition-status" role="status" aria-live="polite">Recognition suggests names from the current fret shape and track tuning without capo. It does not change the draft until you apply a name.</p>
      </div>
      <details data-ui="chord-generator" style="flex-basis:100%">
        <summary>Generate chord shapes</summary>
        <p>Generate ordered voicings for this track. Names use tuning without capo; playable pitches include capo. Select a shape to copy it into this draft, then use Apply annotation, Replace voice notes, or Save draft as new.</p>
        <label>Root <select data-gen="root" aria-label="Generator root">${['C','C# / Db','D','D# / Eb','E','F','F# / Gb','G','G# / Ab','A','A# / Bb','B'].map((n,i)=>`<option value="${i}">${n}</option>`).join('')}</select></label>
        <label>Quality <select data-gen="quality" aria-label="Generator quality">${['M','7','maj7','6','m','m7','m/maj7','m6','sus2','sus4','7sus2','7sus4','dim','dim7','aug','5'].map(q=>`<option>${q}</option>`).join('')}</select></label>
        <label>Bass <select data-gen="bass" aria-label="Generator bass"><option value="">Root</option>${['C','C# / Db','D','D# / Eb','E','F','F# / Gb','G','G# / Ab','A','A# / Bb','B'].map((n,i)=>`<option value="${i}">${n}</option>`).join('')}</select></label>
        <label>Extension <select data-gen="extension" aria-label="Generator extension"><option value="0">None</option><option>9</option><option>11</option><option>13</option></select></label>
        ${[['extension_shift','Extension alteration'],['fifth_shift','Fifth alteration'],['ninth_shift','Ninth alteration'],['eleventh_shift','Eleventh alteration']].map(([k,n])=>`<label>${n} <select data-gen="${k}" aria-label="${n}"><option value="0">Natural</option><option value="-1">Lower</option><option value="1">Raise</option></select></label>`).join('')}
        <label><input data-gen="add" type="checkbox">Add extension</label>
        <label>Names <select data-gen="sharp" aria-label="Generator name spelling"><option value="true">Sharps</option><option value="false">Flats</option></select></label>
        <label>Profile <select data-gen="profile" aria-label="Generator profile"><option value="normal">Normal</option><option value="inversions">Inversions</option><option value="close-voiced">Close voiced</option><option value="open-voiced">Open voiced</option></select></label>
        <label>Minimum fret <input data-gen="min_fret" aria-label="Generator minimum fret" type="number" min="0" max="15" step="1" value="0"></label>
        <label>Maximum fret <input data-gen="max_fret" aria-label="Generator maximum fret" type="number" min="0" max="25" step="1" placeholder="Track default"></label>
        <label><input data-gen="open_strings" type="checkbox">Include open strings below minimum fret</label>
        <label>Maximum results <input data-gen="count" aria-label="Generator result count" type="number" min="1" max="100" step="1" value="30"></label>
        <button type="button" data-action="chord-generate">Generate shapes</button>
        <p data-ui="generation-status" role="status" aria-live="polite"></p>
        <div data-ui="generated-chords" aria-label="Generated chord shapes in source order" style="display:flex;flex-wrap:wrap;gap:8px;max-height:360px;overflow:auto"></div>
      </details>
      <details data-ui="chord-library" style="flex-basis:100%">
        <summary>Custom chord library</summary>
        <p>Saved fret shapes are shared across your songs. They store string positions, not tuning: the same shape can produce different pitches on another tuning or capo. Loading changes only this draft. Save, Rename and Remove from library save immediately, even if you cancel this dialog; song Undo does not undo library changes.</p>
        <label>Saved shape <select data-ui="library-chord" aria-label="Saved chord shape"></select></label>
        <button type="button" data-action="library-refresh">Refresh library</button>
        <button type="button" data-action="library-load" disabled>Load into draft</button>
        <label>Name in library <input data-ui="library-name" aria-label="Name in chord library" maxlength="8192"></label>
        <button type="button" data-action="library-add" disabled>Save draft as new</button>
        <button type="button" data-action="library-rename" disabled>Rename saved shape</button>
        <button type="button" data-action="library-remove" disabled>Remove from library</button>
        <p data-ui="library-status" role="status" aria-live="polite"></p>
      </details>
      <div style="flex-basis:100%">
        <label>Entry velocity <input data-ui="chord-velocity" aria-label="Chord note entry velocity" type="number" min="0" max="127" step="1" value="95"></label>
        <p data-ui="chord-notes-preview"></p>
        <p data-ui="chord-ties-preview"></p>
        <label><input data-ui="chord-remove-ties" type="checkbox">Remove all ties touching replaced notes across every occurrence; surviving continuations become fresh attacks</label>
        <button type="button" data-action="chord-notes">Replace voice notes from diagram</button>
      </div>
    </form>
    <form class="vt-tab-setup vt-tab-curve vt-tab-panel" data-panel="curve" hidden aria-label="Pitch curve editor">
      <strong data-ui="curve-title"></strong>
      <label>Preset <select data-ui="curve-preset"></select></label>
      <label>Points <textarea data-ui="curve-points" rows="3" cols="34" aria-label="Curve position:value points" style="font:inherit;color:inherit;background:var(--panel,#20292e);max-width:100%"></textarea></label>
      <button type="submit" data-ui="curve-apply">Apply curve</button>
      <button type="button" data-action="remove-curve">Remove curve</button>
      <button type="button" data-action="close-curve">Cancel</button>
      <p data-ui="curve-help"></p><p data-ui="curve-status" role="status" aria-live="polite"></p>
      <svg data-ui="curve-preview" viewBox="0 0 360 140" role="img" aria-label="Pitch curve preview" style="width:360px;max-width:100%;height:140px"></svg>
    </form>
    <form class="vt-tab-transpose vt-tab-panel" data-panel="transpose" aria-label="Transpose" hidden>
      <label>Semitones <input data-ui="transpose-semitones" type="number" min="-12" max="12" value="0" required></label>
      <label>Apply to <select data-ui="transpose-scope"><option value="track" selected>the whole track</option><option value="measure">the caret's measure</option><option value="selection">the selected phrase</option></select></label>
      <label><input type="checkbox" data-ui="transpose-all" checked> All tracks</label>
      <label><input type="checkbox" data-ui="transpose-chords" checked> Apply to chords</label>
      <label><input type="checkbox" data-ui="transpose-strings" checked> Try to keep strings</label>
      <p>As TuxGuitar's Transpose: percussion tracks are skipped; notes that would leave the instrument refuse, nothing is removed.</p>
      <button type="submit">Transpose</button><button type="button" data-action="close-transpose">Close</button>
    </form>
    <form class="vt-tab-measures vt-tab-panel" data-panel="measures" aria-label="Measures" hidden>
      <div role="group" aria-label="Measure menu" title="TuxGuitar's Measure menu: measures by number, as the order list counts them">Measures <input data-ui="ops-from" type="number" min="1" value="1" style="width:4em" aria-label="First measure"> to <input data-ui="ops-to" type="number" min="1" value="1" style="width:4em" aria-label="Last measure"> × <input data-ui="ops-count" type="number" min="1" max="100" value="1" style="width:3.5em" aria-label="How many to add or paste"><button type="button" data-action="measure-add-before">Add before</button><button type="button" data-action="measure-add-after">Add after</button><button type="button" data-action="measure-remove">Remove</button><button type="button" data-action="measure-clean" title="Remove this track's notes and rests in these measures">Clean</button><button type="button" data-action="measure-copy">Copy</button><label><input data-ui="ops-all" type="checkbox">all tracks</label><button type="button" data-action="measure-paste" title="Replace from the first measure on">Paste</button><button type="button" data-action="measure-paste-insert" title="Insert before the first measure">Insert paste</button><label>Move before measure <input data-ui="ops-destination" type="number" min="1" value="1" style="width:4em" aria-label="Move before measure (last plus one appends)"></label><button type="button" data-action="measure-move">Move passage</button></div>
      <div><button type="button" data-action="measure-unique" title="Clone reused patterns for these occurrences in one Undo">Make passage unique</button><label><input data-ui="ops-headers" type="checkbox">Copy meter, repeats and staff headers</label><label><input data-ui="ops-markers" type="checkbox">Copy markers</label><span title="Portable measure copies include score notes, not raw tracker effects">Score parts only</span></div>
      <div data-ui="ops-track-map" role="group" aria-label="Measure paste tracks"></div>
      <label>Measure <select data-ui="measure"></select></label>
      <label>From occurrence <select data-ui="measure-from-occ"></select></label><label>At quarter notes <input data-ui="measure-from" value="0" required></label>
      <label>To occurrence <select data-ui="measure-to-occ"></select></label><label>At quarter notes <input data-ui="measure-to" value="1" required></label>
      <label>Meter <input data-ui="meter-n" type="number" min="1" max="64" value="1" required>/<select data-ui="meter-d"><option>1</option><option>2</option><option selected>4</option><option>8</option><option>16</option><option>32</option><option>64</option></select></label><label title="TuxGuitar's time signature 'to the end': this and every later measure take the meter"><input data-ui="meter-to-end" type="checkbox">to the end</label>
      <label>Swing <select data-ui="measure-swing" aria-label="Measure swing"><option value="none">Straight</option><option value="eighth">Swing eighths</option><option value="sixteenth">Swing sixteenths</option></select></label><label title="How the tempo is written (TuxGuitar's tempo base): the playback tempo stays the same">Beat unit <select data-ui="tempo-unit"><option value="4">quarter</option><option value="4.">dotted quarter</option><option value="8">eighth</option><option value="8.">dotted eighth</option><option value="2">half</option><option value="2.">dotted half</option><option value="16">16th</option><option value="1">whole</option></select></label>
      <label><input data-ui="measure-repeat-open" type="checkbox">Repeat start</label>
      <label>Repeat end: additional passes <input data-ui="measure-repeat-close" type="number" min="0" max="100" step="1" value="0" required aria-label="Repeat additional passes"></label>
      <span data-ui="measure-endings" role="group" aria-label="Alternate endings" title="TuxGuitar's alternate endings: the passes that play this measure. Endings already taken since the last repeat start are disabled">Endings${[1, 2, 3, 4, 5, 6, 7, 8].map(i => `<label><input type="checkbox" data-ending="${i}">${i}</label>`).join('')}</span>
      <p>Repeat end 0 means no repeat end; 1 plays the section twice. Endings are the passes 1–8 that play this measure; none clears them. Repeats require explicit measures covering the whole song, with endpoints on tracker rows. Measures can span orders or divide a pattern. Fractional-row boundaries and written beats crossing a measure boundary are refused; split and tie those beats explicitly.</p>
      <label>Marker title <input data-ui="marker-title" maxlength="4096" style="width:240px" placeholder="Blank removes marker"></label>
      <label>Marker color <input data-ui="marker-color" pattern="#[0-9a-fA-F]{6}" placeholder="#rrggbb" aria-label="Marker color (optional)" style="width:90px"></label>
      <button type="submit">Apply measure</button><button type="button" data-action="delete-measure" title="Remove this measure entry (meter, marker, repeats); its notes and time stay">Clear entry</button><button type="button" data-action="close-measures">Close</button>
      <p>Endpoints are exact quarter-note offsets within each order occurrence. Their span must equal the meter. Swing changes the performed timing of eligible notes; written positions and tempo stay unchanged. Uncovered regions remain unmetered display groups.</p>
      <strong>Tempo at start</strong><span data-ui="tempo-target"></span>
      <span data-ui="tempo-effective"></span>
      <label>Explicit change (BPM) <input data-ui="tempo-bpm" type="number" min="32" max="255" step="1" placeholder="No change" aria-label="Tempo change in BPM"></label>
      <label>Apply to <select data-ui="tempo-scope"><option value="occurrence">This occurrence</option><option value="pattern">Pattern — all uses</option></select></label>
      <button type="button" data-action="tempo-set">Apply tempo</button><button type="button" data-action="tempo-clear">Clear change</button>
      <p data-ui="tempo-help"></p>
      <p>Tempo continues until the next change. Clear removes only the explicit change at this position. Moving measure endpoints does not move an existing tempo change.</p>
    </form>
    <div class="vt-tab-entry"><label><span data-ui="entry-label">Fret</span> <input data-ui="fret" type="number" min="0" max="99" aria-label="Fret" placeholder="0–99"></label>
      <button type="button" data-action="fret">Enter fret</button><button type="button" data-action="preview">Preview</button>
      <button type="button" data-action="chord">Select chord</button>
      <button type="button" data-action="chord-diagram">Chord diagram…</button>
      <button type="button" data-action="copy">Copy selected beats</button><button type="button" data-action="paste" title="Paste the latest beat or measure clipboard; beat paste replaces whole beats in both voices at selection start">Paste</button><button type="button" data-action="paste-safe" title="Paste beats only into empty destination spans">Paste safe</button><button type="button" data-action="paste-replace" title="Replace whole beats in both voices using TuxGuitar timing">Paste replace</button><button type="button" data-action="paste-span" title="Replace only copied voices over the exact phrase span; preserve exterior note fragments and split across bars">Paste span</button><span class="vt-tab-select-row" title="Extend the beat selection from its first beat, as TuxGuitar's Edit &gt; Selection">Select <button type="button" data-action="select-first" title="to the first beat">|◀</button><button type="button" data-action="select-previous" title="to the start of this or the previous measure">◀◀</button><button type="button" data-action="select-left" title="one beat left">◀</button><button type="button" data-action="select-right" title="one beat right">▶</button><button type="button" data-action="select-next" title="to the end of this or the next measure">▶▶</button><button type="button" data-action="select-last" title="to the last beat">▶|</button><button type="button" data-action="select-all" title="every beat of this track (Ctrl+A)">All</button><button type="button" data-action="select-none">None</button></span>
      <button type="button" data-action="cut" title="Ctrl+X: copy beats, then cut selected notes or rests">Cut</button><button type="button" data-action="repeat" title="Ctrl+R: repeat the contiguous selection at the next beat">Repeat</button>
      <button type="button" data-action="paste-mix" title="Merge compatible rhythms and chord notes">Paste mix</button><button type="button" data-action="paste-push" title="Move later material in copied voices to make room">Paste push</button>
      <label>Other voice <select data-ui="voice-transfer-mode"><option value="safe">Empty destination</option><option value="mix">Mix</option><option value="replace">Replace</option></select></label>
      <button type="button" data-action="move-voice">Move to other voice</button><button type="button" data-action="copy-voice">Copy to other voice</button>
      <button type="button" data-action="adopt">Adopt selected Pattern note</button>
      <button type="button" data-action="pitch-down" title="Shift+Left">Semitone −</button><button type="button" data-action="pitch-up" title="Shift+Right">Semitone +</button>
      <button type="button" data-action="string-up" title="Shift+Up">String ↑</button><button type="button" data-action="string-down" title="Shift+Down">String ↓</button>
      <label>Spelling letter <select data-ui="spelling-step"><option>C</option><option>D</option><option>E</option><option>F</option><option>G</option><option>A</option><option>B</option></select></label>
      <label>Accidental <select data-ui="spelling-alter"><option value="auto">Automatic</option><option value="0">Natural</option><option value="1">Sharp ♯</option><option value="-1">Flat ♭</option><option value="2">Double sharp</option><option value="-2">Double flat</option></select></label>
      <button type="button" data-action="spelling">Apply spelling</button><button type="button" data-action="enharmonic" title="E">Enharmonic</button>
      <label>At (quarter notes) <input data-ui="at" value="0" aria-label="Beat position"></label><button type="button" data-action="go">Go</button>
      <span data-ui="cursor"></span></div>
    <div class="vt-tab-entry"><label>Beat text <textarea data-ui="beat-text" maxlength="4096" rows="2" cols="40" aria-label="Beat text" style="font:inherit;color:inherit;background:var(--panel,#20292e);max-width:100%"></textarea></label>
      <button type="button" data-action="beat-text">Apply text</button></div>
    <p class="vt-tab-status" role="status" aria-live="polite"></p>
    <div class="vt-tab-grid" aria-label="String and beat entry"></div>
    <div class="vt-tab-raw" aria-label="Existing Pattern notes"></div>
    <p class="vt-tab-help">Click a string and type a fret. Two digits within 1 second combine when playable. ↑↓ strings · ←→ beats · Ctrl+←→ previous/next measure · Ctrl+Shift+←→ first/last measure · Ctrl+Shift+↑↓ previous/next track · Shift+←→ semitone · Shift+↑↓ move note to adjacent string at the same pitch · E enharmonic · +/− longer/shorter (clears dots) · L tie · * dotted · / triplet · X dead · O ghost · H hammer · P palm mute · S slide · V vibrato · F fade-in · Delete note · Ins insert rest · Ctrl+Delete clean beat · Ctrl+A select all · Ctrl+1/2 voice · Alt(+Shift)+←→ next/previous (last/first) marker · Ctrl+click select multiple beats · Ctrl+C/V copy/paste beats · Ctrl+Z/Y undo/redo. With no authored measures, measure navigation uses order occurrences. F5–F8 use the shared transport.</p>
    <p class="vt-tab-diagnostics"></p><p class="vt-tab-meter"></p><p data-ui="tempo-warning" role="status" hidden></p><div class="vt-tab-score" aria-label="Staff and tablature"></div>`;
    const ui = name => root.querySelector(`[data-ui="${name}"]`);
    const rangeArticulations = ['ghost', 'accent', 'heavy_accent', 'staccato', 'palm_mute', 'dead',
      'let_ring', 'fade_in', 'vibrato', 'slide', 'hammer'];
    function rangeNotes() {
      return selectedGroups().flatMap(group => {
        const order = view.score.order_ids.indexOf(group.occurrence);
        return (view.score.patterns[String(view.orders[order])]?.beats || [])
          .filter(b => b.track === track && b.voice === voice && group.beats.includes(b.id)).flatMap(b => b.notes);
      });
    }
    const grid = root.querySelector('.vt-tab-grid'), scoreHost = root.querySelector('.vt-tab-score');
    const entryHome = ui('fret').closest('.vt-tab-entry'), entryLabel = ui('fret').closest('label');
    const entryButton = root.querySelector('[data-action=fret]'), drumEntry = text('div', '', 'vt-tab-entry');
    drumEntry.append(text('span', 'Keys 1–100 · unsupported techniques and guitar chords are disabled.'));
    drumEntry.hidden = true;
    root.querySelector('.vt-tab-tools').after(drumEntry);
    // Keep the engraving in view; all existing controls keep their handlers.
    const inspector = document.createElement('details'); inspector.className = 'vt-tab-inspector';
    inspector.append(text('summary', 'Note and beat properties · navigation'));
    const properties = text('div', '', 'vt-tab-tools');
    let property = ui('beat-stem').closest('label');
    const stop = root.querySelector('[data-action=delete]');
    while (property && property !== stop) {
      const next = property.nextSibling; properties.append(property); property = next;
    }
    inspector.append(properties, root.querySelector('.vt-tab-nav'), ...[...root.querySelectorAll('.vt-tab-entry')].filter(e => e !== drumEntry));
    root.querySelector('.vt-tab-tools').after(inspector);
    // Advanced commands belong with the inspector, whose height is bounded so the
    // score stays reachable even while editing a large set of properties.
    const advanced = text('div', '', 'vt-tab-tools');
    let extra = root.querySelector('[data-action=delete-beat]');
    const undo = root.querySelector('[data-action=undo]');
    while (extra && extra !== undo) {
      const next = extra.nextSibling; advanced.append(extra); extra = next;
    }
    inspector.append(advanced);
    // View choices are local presentation preferences, never score edits or Undo entries.
    const viewDefaults = {layout: 'horizontal', scale: 80, notation: 'both', multitrack: true, compact: false, chordNames: true, chordDiagrams: true, dynamics: false, pitch: 'tuxguitar'};
    function viewPreferences(value) {
      value = {...viewDefaults, ...(value && typeof value === 'object' ? value : {})};
      return {layout: ['horizontal', 'page'].includes(value.layout) ? value.layout : viewDefaults.layout,
        scale: Number.isFinite(value.scale) ? Math.min(200, Math.max(50, value.scale)) : viewDefaults.scale,
        notation: ['both', 'staff', 'tab'].includes(value.notation) ? value.notation : 'both',
        multitrack: value.multitrack === true, compact: value.compact === true,
        chordNames: value.chordNames !== false, chordDiagrams: value.chordDiagrams !== false,
        dynamics: value.dynamics === true, pitch: ['tuxguitar', 'concert'].includes(value.pitch) ? value.pitch : viewDefaults.pitch};
    }
    let viewPrefs = {...viewDefaults};
    try { viewPrefs = viewPreferences(JSON.parse(localStorage.getItem('vt.scoreView') || 'null')); } catch (_) {}
    const presentation = document.createElement('details'); presentation.className = 'vt-tab-view';
    presentation.innerHTML = `<summary>Score view <button type="button" data-ui="view-tuxguitar">TuxGuitar layout</button></summary><div class="vt-tab-tools">
      <label>Layout <select data-ui="view-layout"><option value="page">Page</option><option value="horizontal">Horizontal</option></select></label>
      <label>Zoom <input data-ui="view-scale" aria-label="Score zoom percent" type="number" min="50" max="200" step="10">%</label>
      <button type="button" data-ui="view-reset-scale">100%</button>
      <label>Notation <select data-ui="view-notation"><option value="both">Staff and TAB</option><option value="staff">Staff</option><option value="tab">TAB</option></select></label>
      <label><input type="checkbox" data-ui="view-multitrack">All tracks</label>
      <label title="TuxGuitar compact beat spacing. Available when displaying one track."><input type="checkbox" data-ui="view-compact">Compact spacing</label>
      <label><input type="checkbox" data-ui="view-chord-names">Chord names</label>
      <label><input type="checkbox" data-ui="view-chord-diagrams">Chord diagrams</label>
      <label><input type="checkbox" data-ui="view-dynamics">Printed dynamics</label>
      <label>Staff pitch <select data-ui="view-pitch"><option value="concert">Sounding</option><option value="tuxguitar">TuxGuitar written</option></select></label>
      </div><p class="vt-tab-help">View preferences are saved on this computer. Percussion always uses the staff. Print preview has its own settings.</p>`;
    inspector.after(presentation);
    const viewFields = {layout: 'layout', scale: 'scale', notation: 'notation', multitrack: 'multitrack', compact: 'compact', chordNames: 'chord-names', chordDiagrams: 'chord-diagrams', dynamics: 'dynamics', pitch: 'pitch'};
    listen(ui('view-tuxguitar'), 'click', e => {e.preventDefault();e.stopPropagation();
      viewPrefs = {...viewPrefs, layout: 'horizontal', multitrack: true, notation: 'both', scale: 80, dynamics: false, pitch: 'tuxguitar'};
      presentation.open = true;saveViewPreferences();});
    function showViewPreferences() {
      for (const [key, suffix] of Object.entries(viewFields)) {
        const field = ui('view-' + suffix);
        if (field.type === 'checkbox') field.checked = viewPrefs[key]; else field.value = viewPrefs[key];
      }
      ui('view-compact').disabled = viewPrefs.multitrack && Object.keys(view?.score?.tracks || {}).length > 1;
    }
    function saveViewPreferences() {
      showViewPreferences();
      try { localStorage.setItem('vt.scoreView', JSON.stringify(viewPrefs)); } catch (_) {}
      engrave();
    }
    showViewPreferences();
    listen(presentation, 'change', e => {
      const key = Object.keys(viewFields).find(key => e.target === ui('view-' + viewFields[key]));
      if (!key) return;
      viewPrefs = viewPreferences({...viewPrefs, [key]: e.target.type === 'checkbox' ? e.target.checked :
        key === 'scale' ? (e.target.value.trim() ? Number(e.target.value) : 100) : e.target.value});
      saveViewPreferences();
    });
    listen(ui('view-reset-scale'), 'click', () => { viewPrefs.scale = 100; saveViewPreferences(); });
    root.querySelector('[data-action=setup]').textContent = 'Track setup';
    const quickNavigation = text('div', '', 'vt-tab-quick-nav');
    quickNavigation.innerHTML = `<button type="button" data-action="quick-previous">◀ Bar</button>
      <label>Go to bar <input data-ui="jump-bar" type="number" min="1" value="1" aria-label="Go to bar"></label>
      <button type="button" data-action="jump-bar">Go</button><button type="button" data-action="quick-next">Bar ▶</button>
      <button type="button" data-action="workspace-focus" title="Collapse editing panels and focus the score">Focus score</button>`;
    root.querySelector('.vt-tab-tools').append(quickNavigation);
    const independent = text('label', '');
    independent.innerHTML = '<input type="checkbox" data-ui="independent">Independent measures';
    independent.title = 'Phrase and measure commands make reused occurrences independent first, in the same Undo. Structural commands also prepare fully measured patterns as individual bars. Individual note properties retain their existing pattern scope.';
    quickNavigation.append(independent);
    const prepare = text('button', 'Prepare independent measures'); prepare.type = 'button'; prepare.dataset.action = 'prepare-measures';
    prepare.title = 'Prepare the entire fully measured score as independent one-bar patterns. One Undo restores the original arrangement. Unsafe timing or automation refuses without changes.';
    root.querySelector('[data-action=measure-unique]').after(prepare);
    const gridDetails = document.createElement('details'); gridDetails.className = 'vt-tab-grid-details';
    gridDetails.append(text('summary', 'String grid (optional)'), grid);
    scoreHost.after(gridDetails);
    const help = document.createElement('details'); help.className = 'vt-tab-keyboard-help';
    help.append(text('summary', 'Keyboard shortcuts'), root.querySelector(':scope > .vt-tab-help')); root.append(help);
    const entryHelp = text('p', '', 'vt-tab-help'); scoreHost.before(entryHelp);
    let boardPrefs = {...fretboardDefaults}, boardPending = false, boardKey = '', boardPlayback = null;
    try { boardPrefs = fretboardPreferences(JSON.parse(localStorage.getItem('vt.fretboard') || 'null')); } catch (_) {}
    const board = document.createElement('details'); board.className = 'vt-fretboard'; board.open = boardPrefs.open;
    board.innerHTML = `<summary>Fretboard and scales (optional)</summary>
      <div class="vt-tab-tools">
        <label>Root <select data-fb="root" aria-label="Scale root"></select></label>
        <label>Scale <select data-fb="scale" aria-label="Reference scale"></select></label>
        <label>Hand <select data-fb="direction"><option value="right">Right</option><option value="left">Left</option></select></label>
        <label>Click <select data-fb="mode"><option value="edit">Toggle note</option><option value="audition">Audition only</option></select></label>
      </div>
      <details class="vt-fretboard-settings"><summary>Fretboard appearance</summary><div class="vt-tab-tools">
        <label><input data-fb="noteText" type="checkbox">Note text</label>
        <label><input data-fb="scaleText" type="checkbox">Scale text</label>
        <label>Font <input data-fb="font" maxlength="80"></label>
        <label>Size <input data-fb="size" type="number" min="8" max="24"></label>
        <label><input data-fb="bold" type="checkbox">Bold</label><label><input data-fb="italic" type="checkbox">Italic</label>
        <label>String spacing <input data-fb="spacing" type="number" min="20" max="60" step="2"></label>
        <label>Background <input data-fb="background" type="color"></label><label>Strings <input data-fb="strings" type="color"></label>
        <label>Fret markers <input data-fb="points" type="color"></label><label>Notes <input data-fb="notes" type="color"></label>
        <label>Scale <input data-fb="scaleColor" type="color"></label><button type="button" data-fb="reset">Reset appearance</button>
      </div></details>
      <p class="vt-tab-help" data-fb="context"></p>
      <div class="vt-fretboard-scroll"><svg aria-label="Fretboard positions"></svg></div>
      <p class="vt-tab-help">Concert pitch includes capo. Click toggles a note across both voices; Shift+click auditions only. Arrow keys move on the board; Enter/Space uses the selected click mode. Reference scales do not change the song.</p>`;
    gridDetails.before(board);
    const fb = name => board.querySelector(`[data-fb="${name}"]`), boardSvg = board.querySelector('svg');
    fb('root').replaceChildren(...scaleRoots.map(name => { const o = text('option', name); o.value = name; return o; }));
    fb('scale').replaceChildren(...[['None', 0], ...scaleCatalogue].map(([name], i) => {
      const o = text('option', name); o.value = i - 1; return o;
    }));
    function boardPreferenceControls() {
      for (const [k, value] of Object.entries(boardPrefs)) if (fb(k)) {
        if (typeof value === 'boolean') fb(k).checked = value; else fb(k).value = value;
      }
    }
    function saveBoardPreferences() {
      try { localStorage.setItem('vt.fretboard', JSON.stringify(boardPrefs)); } catch (_) {}
    }
    boardPreferenceControls();
    listen(board, 'toggle', e => {
      if (e.target !== board) return;
      boardPrefs.open = board.open; saveBoardPreferences(); drawFretboard();
    });
    listen(board, 'change', e => {
      const key = e.target.dataset.fb;
      if (key === 'mode') { drawFretboard(); return; }
      if (!(key in fretboardDefaults)) return;
      boardPrefs = fretboardPreferences({...boardPrefs, [key]: e.target.type === 'checkbox' ? e.target.checked :
        ['size', 'spacing', 'scale'].includes(key) ? Number(e.target.value) : e.target.value});
      boardPreferenceControls(); saveBoardPreferences(); drawFretboard(); drawPiano();
    });
    listen(fb('reset'), 'click', () => {
      boardPrefs = {...fretboardDefaults, open: board.open, root: boardPrefs.root, scale: boardPrefs.scale};
      boardPreferenceControls(); saveBoardPreferences(); drawFretboard(); drawPiano();
    });
    listen(board, 'keydown', e => {
      // Board controls must not trigger TAB digits/navigation or host note entry.
      if (!/^F[5-8]$/.test(e.key)) e.stopPropagation();
      const cell = e.target.closest('[data-fb-string]'); if (!cell) return;
      let s = +cell.dataset.fbString, f = +cell.dataset.fbFret;
      if (['Enter', ' '].includes(e.key)) { e.preventDefault(); void useFretboard(s, f, e.shiftKey); return; }
      if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
      e.preventDefault();
      if (e.key === 'ArrowUp') s--; if (e.key === 'ArrowDown') s++;
      if (e.key === 'ArrowLeft') f += boardPrefs.direction === 'left' ? 1 : -1;
      if (e.key === 'ArrowRight') f += boardPrefs.direction === 'left' ? -1 : 1;
      const next = boardSvg.querySelector(`[data-fb-string="${s}"][data-fb-fret="${f}"]`);
      if (next) { cell.tabIndex = -1; next.tabIndex = 0; next.focus({preventScroll: true}); next.scrollIntoView({block: 'nearest', inline: 'nearest'}); }
    });
    listen(boardSvg, 'click', e => {
      const cell = e.target.closest('[data-fb-string]'); if (cell) void useFretboard(+cell.dataset.fbString, +cell.dataset.fbFret, e.shiftKey);
    });
    const piano = document.createElement('details'); piano.className = 'vt-piano';
    piano.innerHTML = `<summary>Piano (optional)</summary><div class="vt-tab-tools">
      <button type="button" data-piano="previous">Previous beat</button><button type="button" data-piano="next">Next beat</button>
      <label>Click <select data-piano="mode"><option value="edit">Toggle note</option><option value="audition">Audition only</option></select></label>
      <span data-piano="context"></span></div><div class="vt-piano-scroll"><div class="vt-piano-keys" aria-label="Native piano keys"></div></div>
      <p class="vt-tab-help">Uses the selected voice, exact caret and duration above. Shift+click auditions. Arrow keys move between keys; Enter/Space activates.
      Scale highlights share the fretboard selection. Bare rests may be split at the caret; sounding notes and annotated rests are protected.</p>`;
    board.after(piano);
    let workspacePrefs = {};
    try { workspacePrefs = JSON.parse(localStorage.getItem('vt.scoreWorkspace') || '{}') || {}; } catch (_) {}
    const workspacePanels = {inspector, grid:gridDetails, piano, shortcuts:help};
    for (const [name, element] of Object.entries(workspacePanels)) {
      element.open = workspacePrefs[name] === true;
      listen(element, 'toggle', () => {
        workspacePrefs[name] = element.open;
        try { localStorage.setItem('vt.scoreWorkspace', JSON.stringify(workspacePrefs)); } catch (_) {}
      });
    }
    const pk = name => piano.querySelector(`[data-piano="${name}"]`), pianoKeys = piano.querySelector('.vt-piano-keys');
    let pianoKey = '', pianoFocus = 60;
    listen(piano, 'toggle', () => { if (piano.open) { drawPiano(); pianoKeys.querySelector('[tabindex="0"]')?.scrollIntoView({block: 'nearest', inline: 'center'}); } });
    listen(pk('mode'), 'change', drawPiano);
    listen(pk('previous'), 'click', () => move(-1)); listen(pk('next'), 'click', () => move(1));
    listen(pianoKeys, 'click', e => {
      const key = e.target.closest('[data-piano-pitch]');
      if (key) { pianoFocus = +key.dataset.pianoPitch; void enterPitch(pianoFocus, {audition: e.shiftKey || pk('mode').value === 'audition'}); }
    });
    listen(piano, 'keydown', e => {
      if (!/^F[5-8]$/.test(e.key)) e.stopPropagation();
      const key = e.target.closest('[data-piano-pitch]'); if (!key) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault(); if (!e.repeat) void enterPitch(+key.dataset.pianoPitch, {audition: e.shiftKey || pk('mode').value === 'audition'}); return;
      }
      const delta = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: 12, ArrowDown: -12}[e.key];
      if (!delta) return;
      e.preventDefault();
      const next = pianoKeys.querySelector(`[data-piano-pitch="${+key.dataset.pianoPitch + delta}"]`);
      if (next) { key.tabIndex = -1; next.tabIndex = 0; pianoFocus = +next.dataset.pianoPitch; next.focus({preventScroll: true}); next.scrollIntoView({block: 'nearest', inline: 'nearest'}); }
    });
    const rawHost = root.querySelector('.vt-tab-raw');
    const status = message => { root.querySelector('.vt-tab-status').textContent = message; };
    const spec = () => view?.score?.tracks?.[track];
    const rawPreview = () => !!view && !view.native && !Object.keys(view.score?.tracks || {}).length;
    let previewChannel = -1, previewOccurrences = [];
    const TECHNIQUE_KEYS = {x: 'dead', o: 'ghost', h: 'hammer', p: 'palm-mute', s: 'slide', v: 'vibrato', f: 'fade-in'};
    const drumActions = new Set(['chord-diagram', 'remove-chord-diagram', 'chord-notes', 'chord-recognize',
      'recognition-apply', 'chord-generate', 'library-load', 'pitch-down', 'pitch-up', 'spelling', 'enharmonic',
      'stroke', 'pick-stroke', 'fade-in', 'tap-slap-pop',
      'vibrato', 'slide', 'bend', 'tremolo-bar', 'hammer', 'harmonic']);
    const percussionRefusal = () => status('This technique or guitar operation is not supported on percussion tracks.');
    const drumDisabled = new Map();
    const allBeats = () => resolvedBeats(view, view.pattern);
    const beats = () => allBeats().filter(b => b.track === track && b.voice === voice).sort((a, b) => cmp(a.at, b.at));
    const current = () => ambiguousSelection ? null : beats().find(b => cmp(b.at, at) === 0);
    const authoredBeat = (beat, pattern = view.pattern) => {
      const source = view.score.patterns[pattern]?.beats.find(b => b.id === beat.id);
      if (!source) throw new Error('The selected beat no longer exists.');
      return clone(source); // Never persist resolved placement, shared annotations or engraving metadata.
    };
    const occurrence = () => view?.score?.order_ids?.[view.order];
    const rawRecords = () => (view?.raw_positions || []).filter(p => atOccurrence(p, view, view.pattern));
    const rowStep = () => view?.score?.patterns?.[view.pattern]?.row_step || view?.row_step || [1, 4];
    const rowCount = () => Array.isArray(view?.rows) ? view.rows[view.pattern_names?.indexOf(view.pattern)] || 64 : Number(view?.rows) || 64;
    const end = () => rat(rowStep()[0] * rowCount(), rowStep()[1]);
    const entryKey = () => JSON.stringify([view?.song, view?.pattern, view?.order, track, voice, at, string]);
    function selection() {
      const b = current(), n = chosen === 'chord' ? null : b?.notes?.find(n => n.string === string);
      const link = n && (view.positions || []).find(p => p.kind === 'note' && atOccurrence(p, view, view.pattern) && p.note === n.id);
      const ch = link?.ch ?? n?.channel ?? spec()?.channels?.[string - 1];
      const row = rat(at[0] * rowStep()[1], at[1] * rowStep()[0]);
      return {track, voice, pattern: view?.pattern, occurrence: occurrence(), order: view?.order,
        id: link?.id || null, at: [...at], string, beat: b?.id || null, note: n?.id || null, chord: chosen === 'chord',
        channel: ch, ch, row: view.native || Array.isArray(link?.row) ? row : num(row)};
    }
    function choose(nextAt, nextString = string, chord = false, notify = true, extend = false) {
      ambiguousSelection = false;
      if (notify) navigationEcho = null;
      rawSelected = null;
      at = [...nextAt]; string = Math.max(1, Math.min(spec()?.tuning.length || 1, nextString)); chosen = chord ? 'chord' : null;
      pending = ''; const b = current(); if (b) written = clone(b.written);
      if (!extend || rangeSelection.length) { selectedBeats.clear(); selectedNotes.clear(); selectionAnchor = null; rangeSelection = []; }
      if (extend && !selectionAnchor) selectionAnchor = {occurrence: occurrence(), at: [...at]};
      if (b) {
        const ids = chord ? b.notes.map(n => n.id) : b.notes.filter(n => n.string === string).map(n => n.id);
        const previous = selectedNotes.get(b.id);
        if (extend && previous && (chord || !ids.length || ids.every(id => previous.has(id)))) {
          if (chord || !ids.length) { selectedNotes.delete(b.id); selectedBeats.delete(b.id); }
          else { ids.forEach(id => previous.delete(id)); if (!previous.size) { selectedNotes.delete(b.id); selectedBeats.delete(b.id); } }
        } else {
          const notes = previous || new Set(); ids.forEach(id => notes.add(id));
          selectedNotes.set(b.id, notes); selectedBeats.add(b.id);
        }
      }
      if (!selectedBeats.size) selectionAnchor = null;
      controls(); drawGrid(); drawRaw(); markEditCaret();
      if (notify) { notifying = true; try { host.select(selection()); } finally { notifying = false; } }
    }
    function controls() {
      const focused = document.activeElement;
      host.trackChanged?.(track);
      const automaticFree = (view?.measure_errors || []).some(e => e.automatic_free && e.occurrence === occurrence() &&
        e.track === track && cmp(e.at, at) <= 0 && cmp(at, e.end) < 0);
      ui('free-edit').checked = freeRequested || automaticFree;
      ui('free-edit').disabled = automaticFree;
      ui('free-required').hidden = !automaticFree;
      const context = JSON.stringify([entryKey(), occurrence(), !!rawSelected, ambiguousSelection]);
      if (context !== fretContext) { fretContext = context; fretEpoch++; lastDigit = null; }
      const drums = isPercussion(spec());
      for (const [button, previous] of drumDisabled) { button.disabled = previous.disabled; button.title = previous.title; }
      drumDisabled.clear();
      lyricsControls();
      ui('beat-text').value = current()?.text || '';
      ui('beat-text').disabled = busy || !!rawSelected || !current() || !view?.editable;
      root.querySelector('[data-action="beat-text"]').disabled = ui('beat-text').disabled;
      ui('beat-stem').value = current()?.stem || 'inherit';
      ui('stroke-direction').value = current()?.stroke?.direction || '';
      ui('stroke-value').value = current()?.stroke?.value || 16;
      ui('pick-stroke').value = current()?.pick_stroke || '';
      for (const key of ['stroke-direction', 'stroke-value', 'pick-stroke']) ui(key).disabled = ui('beat-text').disabled || !view?.native;
      ui('stroke-value').disabled ||= !current()?.stroke;
      for (const key of ['stroke', 'pick-stroke']) root.querySelector(`[data-action="${key}"]`).disabled = ui('beat-text').disabled || !view?.native;
      root.querySelector('[data-action="beat-stem"]').disabled = busy || !!rawSelected || !current()?.notes.length || !view?.editable;
      root.querySelector('[data-action="chord-diagram"]').disabled = busy || !!rawSelected || !current() || !view?.editable || !view?.native;
      root.querySelector('[data-action="delete-track"]').disabled = busy || !spec() || !view?.editable || ui('name').value !== track;
      ui('duration').value = written.value; ui('dots').value = written.dots || 0;
      ui('range-duration').hidden = !crossRange();
      ui('range-duration').textContent = `Duration changes selected voice ${voice + 1}, original beats only; onsets stay unless Fit moves them.`;
      ui('tuple-n').value = (written.tuplet || [1, 1])[0]; ui('tuple-d').value = (written.tuplet || [1, 1])[1];
      ui('fit').disabled = busy || boardPending || !view?.native || !view?.editable || !!rawSelected || !current();
      if (focused !== ui('at')) ui('at').value = at[1] === 1 ? at[0] : at.join('/');
      const n = rawSelected || current()?.notes?.find(n => n.string === string);
      ui('spelling-step').value = n?.spelling?.step || (n ? keySpelling(n.pitch, spec()?.key?.fifths).step : 'C');
      ui('spelling-alter').value = n?.spelling ? String(n.spelling.alter || 0) : 'auto';
      ui('spelling-step').disabled = ui('spelling-alter').value === 'auto';
      for (const action of ['spelling', 'enharmonic']) root.querySelector(`[data-action="${action}"]`).disabled = busy || !!rawSelected || !n || chosen === 'chord' || !view?.editable;
      ui('fret').value = pending || (n?.fret ?? '');
      ui('fret').max = drums ? 100 : spec()?.max_fret ?? 29;
      ui('fret').min = drums ? 1 : 0; ui('fret').placeholder = drums ? '1–100' : '0–' + ui('fret').max;
      ui('fret').setAttribute('aria-label', drums ? 'Drum key' : 'Fret');
      ui('entry-label').textContent = drums ? 'Drum key' : 'Fret';
      entryButton.textContent = drums ? 'Enter key' : 'Enter fret';
      entryHelp.textContent = rawPreview() ? 'Choose a channel above. Click a staff note to locate its original Pattern cell; edit the music in Pattern.' : drums ? 'Select a staff note or rest, choose a lane, then enter a drum key. ↑↓ lanes · ←→ beats · Ctrl+Z undo. Percussion prints on the staff in every print mode.' :
        'Click a TAB string and type a fret. Arrow keys move the caret · +/− duration · Delete note · Ctrl+Z undo.';
      const destination = drums ? drumEntry : entryHome;
      if (entryLabel.parentElement !== destination) destination.prepend(entryLabel, entryButton);
      drumEntry.hidden = !drums; ui('lane-label').hidden = !drums;
      if (ui('lane').options.length !== (spec()?.tuning.length || 0))
        ui('lane').replaceChildren(...(spec()?.tuning || []).map((_, i) => { const o=text('option', String(i+1));o.value=i+1;return o; }));
      ui('lane').value = string; ui('lane').disabled = busy;
      const tied = n && (view?.score?.ties || []).some(t => t.to.occurrence === occurrence() && t.to.note === n.id);
      root.querySelector('[data-action="tie"]').setAttribute('aria-pressed', String(!!tied));
      const techniqueNotes = noteRange() ? rangeNotes() : current()?.notes.filter(note => chosen === 'chord' ||
        selectedNotes.get(current().id)?.has(note.id)) || [];
      const expressionNotes = techniqueNotes;
      ui('range-expression').hidden = !noteRange();
      ui('range-expression-info').hidden = !noteRange();
      const mixedFlags = rangeArticulations.filter(flag => expressionNotes.some(n => n[flag]) && expressionNotes.some(n => !n[flag]));
      ui('range-expression-info').textContent = mixedFlags.length ? `Mixed: ${mixedFlags.map(k => k.replaceAll('_', ' ')).join(', ')}.` : 'Articulations are uniform across the selected phrase.';
      ui('range-articulation').disabled = busy || !view?.editable || !expressionNotes.length;
      const velocities = new Set(expressionNotes.map(note => note.velocity ?? null));
      const velocity = velocities.size === 1 ? [...velocities][0] : null;
      ui('velocity').value = velocity ?? '';
      ui('velocity').placeholder = velocities.size > 1 ? 'mixed' : 'inherit';
      ui('dynamics').value = velocities.size > 1 ? 'custom' : velocity == null ? '' :
        [15,31,47,63,79,95,111,127].includes(velocity) ? String(velocity) : 'custom';
      for (const field of ['velocity', 'dynamics']) ui(field).disabled =
        busy || !!rawSelected || !view?.editable || !view?.native || !expressionNotes.length;
      root.querySelector('[data-action="velocity"]').disabled = ui('velocity').disabled;
      ui('velocity-info').textContent = noteRange() ? `Selected phrase: ${expressionNotes.length} notes; velocity ${velocities.size > 1 ? 'mixed' : velocity ?? 'instrument default'}.` : current()?.notes.some(n => n.velocity != null) ?
        `Selected beat velocities: ${current().notes.map(n => `string ${n.string ?? n.id}=${n.velocity ?? 'inherit'}`).join(', ')}` : '';
      const harmonics = new Set(techniqueNotes.map(note => JSON.stringify(note.harmonic ?? null)));
      const harmonic = harmonics.size === 1 ? JSON.parse([...harmonics][0]) : null;
      ui('harmonic-type').value = harmonics.size > 1 ? 'mixed' : harmonic?.type || '';
      ui('harmonic-data').value = String(harmonic?.data ?? 0);
      ui('harmonic-type').disabled = ui('velocity').disabled;
      ui('harmonic-data').disabled = ui('velocity').disabled || ['natural', '', 'mixed'].includes(ui('harmonic-type').value);
      root.querySelector('[data-action="harmonic"]').disabled = ui('velocity').disabled;
      const repetitions = new Set(techniqueNotes.map(note => note.trill ? 'trill' : note.tremolo_picking ? 'tremolo_picking' : ''));
      const repetition = repetitions.size === 1 ? [...repetitions][0] : repetitions.size ? 'mixed' : '';
      const rates = new Set(techniqueNotes.map(note => (note.trill || note.tremolo_picking)?.value));
      const frets = new Set(techniqueNotes.filter(note => note.trill).map(note => note.trill.fret));
      ui('repetition-type').value = repetition; ui('repetition-type').disabled = ui('velocity').disabled;
      ui('repetition-type').querySelector('[value="trill"]').disabled = drums;
      ui('repetition-type').querySelector('[value="tremolo_picking"]').textContent = drums ? 'Drum roll' : 'Tremolo picking';
      repetitionRates(repetition, rates.size === 1 ? [...rates][0] : '');
      ui('trill-fret').value = frets.size === 1 ? [...frets][0] : '';
      ui('trill-fret').placeholder = frets.size > 1 ? 'mixed' : 'fret';
      ui('trill-fret').max = spec()?.max_fret ?? 29;
      ui('trill-fret').disabled = ui('velocity').disabled || repetition !== 'trill';
      ui('repetition-value').disabled = ui('velocity').disabled || !['trill', 'tremolo_picking'].includes(repetition);
      root.querySelector('[data-action="repetition"]').disabled = ui('velocity').disabled;
      const graces = new Set(techniqueNotes.map(n => n.grace ? JSON.stringify({
        fret: n.grace.fret, value: n.grace.value, velocity: n.grace.velocity,
        transition: n.grace.transition || 'none', on_beat: !!n.grace.on_beat, dead: !!n.grace.dead}) : 'null'));
      const grace = graces.size === 1 ? JSON.parse([...graces][0]) : null;
      ui('grace-kind').value = graces.size > 1 ? 'mixed' : grace ? 'grace' : '';
      ui('grace-kind').disabled = ui('velocity').disabled;
      ui('grace-fret').value = grace?.fret ?? ''; ui('grace-fret').max = drums ? 100 : spec()?.max_fret ?? 29;
      ui('grace-fret').min = drums ? 1 : 0;
      ui('grace-fret').placeholder = graces.size > 1 ? 'mixed' : drums ? 'drum key' : 'fret';
      ui('grace-key-label').textContent = drums ? 'Grace drum key' : 'Grace fret';
      ui('grace-fret').setAttribute('aria-label', drums ? 'Grace drum key' : 'Grace absolute fret');
      ui('grace-value').value = grace?.value ?? 16; ui('grace-velocity').value = grace?.velocity ?? 47;
      ui('grace-timing').value = grace?.on_beat ? 'on' : 'before';
      ui('grace-transition').value = grace?.transition || 'none'; ui('grace-dead').checked = !!grace?.dead;
      graceControls(); root.querySelector('[data-action="grace"]').disabled = ui('velocity').disabled;
      const marks = new Set(techniqueNotes.map(n => tapSlapPop.find(([flag]) => n[flag])?.[0] || ''));
      ui('tap-slap-pop').value = marks.size > 1 ? 'mixed' : [...marks][0] || '';
      ui('tap-slap-pop').disabled = ui('velocity').disabled;
      root.querySelector('[data-action="tap-slap-pop"]').disabled = ui('velocity').disabled;
      for (const [action, flag] of [['staccato', 'staccato'], ['palm-mute', 'palm_mute'], ['let-ring', 'let_ring'], ['fade-in', 'fade_in'], ['dead', 'dead'], ['vibrato', 'vibrato'], ['slide', 'slide'],
        ['ghost', 'ghost'], ['accent', 'accent'], ['heavy-accent', 'heavy_accent'], ['hammer', 'hammer']]) {
        const notes = techniqueNotes;
        const button = root.querySelector(`[data-action="${action}"]`), count = notes.filter(note => note[flag]).length;
        button.disabled = busy || !!rawSelected || !view?.editable || !view?.native || !notes.length;
        button.setAttribute('aria-pressed', count && count !== notes.length ? 'mixed' : String(!!count));
        if (rangeArticulations.includes(flag)) {
          button.dataset.localTitle ??= button.title;
          button.title = noteRange() ? `${ui('range-articulation').value === 'set' ? 'Set' : 'Clear'} ${flag.replaceAll('_', ' ')} on every selected note.` : button.dataset.localTitle;
        }
      }
      for (const action of ['bend', 'tremolo-bar']) root.querySelector(`[data-action="${action}"]`).disabled =
        busy || !!rawSelected || !view?.editable || !view?.native || !techniqueNotes.length;
      ui('curve-apply').disabled = busy || !view?.editable;
      root.querySelector('[data-action="remove-curve"]').disabled = busy || !view?.editable;
      root.querySelector('[data-action="adopt"]').disabled = busy || !rawSelected || !spec() || !view?.editable ||
        view.native && !rawSelected?.adoptable;
      root.querySelector('[data-action="copy"]').disabled = busy || !!rawSelected || !current() && !selectedBeats.size && !rangeSelection.length;
      root.querySelector('[data-action="paste"]').disabled = busy || !(clipboard || measureClip) || !view?.editable;
      root.querySelector('[data-action="paste-safe"]').disabled = busy || !clipboard || !view?.editable;
      for (const action of ['measure-paste', 'measure-paste-insert']) root.querySelector(`[data-action="${action}"]`).disabled = busy || !measureClip || !view?.editable;
      root.querySelector('[data-action="paste-replace"]').disabled = busy || !clipboard || !view?.editable || !view?.native;
      root.querySelector('[data-action="paste-span"]').disabled = busy || !clipboard || !view?.editable || !view?.native;
      for (const action of ['paste-mix', 'paste-push']) root.querySelector(`[data-action="${action}"]`).disabled = busy || !clipboard || !view?.editable || !view?.native;
      for (const action of ['move-voice', 'copy-voice']) root.querySelector(`[data-action="${action}"]`).disabled = busy || !view?.editable || !view?.native || !selectedBeats.size && !rangeSelection.length || !!host.isPlaying?.();
      for (const action of ['clone-track', 'track-up', 'track-down']) root.querySelector(`[data-action="${action}"]`).disabled = busy || !view?.editable || !spec();
      commandControls();
      ui('cursor').textContent = rawSelected ? `Pattern row ${rawSelected.row} · channel ${rawSelected.ch + 1} · ${rawSelected.reason}` : `${view?.pattern || ''} · ${drums ? 'lane' : 'string'} ${string}${chosen === 'chord' ? ' · chord' : ''}${current()?.duration_source === 'tracker_boundary' ? ' · duration inferred from tracker boundary' : ''}${busy ? ' · saving…' : ''}`;
      for (const b of root.querySelectorAll('[data-action="fret"], [data-action="rest"], [data-action="duration"], [data-action="longer"], [data-action="shorter"], [data-action="delete"], [data-action="delete-beat"], [data-action="remove-unused-voice"], [data-action="clean-beat"], [data-action="insert-rest"], [data-action^="move-beats-"], [data-action="tie"], [data-action^="pitch-"], [data-action^="string-"]')) b.disabled = busy || !!rawSelected || !view?.editable || !spec();
      ui('track').disabled = busy;
      for (const b of root.querySelectorAll('.vt-tab-nav button')) b.disabled = busy || !spec();
      tempoControls();
      for (const action of drumActions) {
        const button = root.querySelector(`[data-action="${action}"]`);
        if (button && drums) {
          drumDisabled.set(button, {disabled: button.disabled, title: button.title});
          button.disabled = true; button.title = 'Not supported on percussion tracks';
        }
      }
      root.querySelector('[data-action=string-up]').textContent = drums ? 'Lane ↑' : 'String ↑';
      root.querySelector('[data-action=string-down]').textContent = drums ? 'Lane ↓' : 'String ↓';
      // Saves can disable their button after an asynchronous preparation step.
      // Retain keyboard Undo at the point focus would otherwise leave the editor.
      if (focused?.tagName === 'BUTTON' && root.contains(focused) && focused.disabled &&
          (document.activeElement === focused || document.activeElement === document.body)) root.focus({preventScroll: true});
      drawFretboard(); drawPiano();
    }
    function entryRefusal() {
      if (destroyed || !spec() || !view?.native) return 'Choose a native track for note entry.';
      if (host.isPlaying?.() || playhead) return 'Stop playback before using note entry or audition.';
      if (rawSelected) return 'Adopt this Pattern note before editing its notation.';
      if (ambiguousSelection) return 'Choose a source note in Pattern, ROLL or TAB before editing an overlapping voice.';
      if (document.querySelector('dialog[open], .modal.on')) return 'Close the dialog before entering notes.';
      if (busy || boardPending) return 'Wait for the current edit to finish.';
      return '';
    }
    function boardRefusal() {
      return entryRefusal() || (isPercussion(spec()) ? 'Choose a native pitched track for the fretboard.' : '');
    }
    function entryTarget(written = readWritten()) {
      return {song: view.song, pattern: view.pattern, order: view.order, occurrence: occurrence(), track, voice,
        at: [...at], string, written, fit: ui('fit').checked, revision: view.revision, beat: current()?.id || null, chord: chosen === 'chord'};
    }
    function sameEntryPosition(target) {
      return !destroyed && view?.song === target.song && view.pattern === target.pattern && view.order === target.order &&
        occurrence() === target.occurrence && track === target.track && voice === target.voice &&
        string === target.string && cmp(at, target.at) === 0 && !rawSelected && !ambiguousSelection;
    }
    async function queueEntry(target, action) {
      boardPending = true; ui('fit').disabled = true; drawFretboard(); drawPiano();
      const job = fretChain.then(async () => {
        await saving;
        if (!sameEntryPosition(target) || (current()?.id || null) !== target.beat ||
          view.revision !== target.revision || !view.editable || host.isPlaying?.() || playhead ||
          document.querySelector('dialog[open], .modal.on'))
          return status('The score or selection changed before note entry; select the position again.');
        return action();
      });
      fretChain = job.catch(() => {});
      try { return await job; } finally { boardPending = false; if (!destroyed) controls(); }
    }
    async function useFretboard(s, fret, audition = false) {
      try {
        const refusal = boardRefusal(); if (refusal) return status(refusal);
        const t = spec(), pitch = t.tuning[s - 1] + (t.capo || 0) + fret;
        if (!Number.isInteger(s) || s < 1 || s > t.tuning.length || !Number.isInteger(fret) ||
          fret < 0 || fret > (t.max_fret ?? 29) || pitch < 0 || pitch > 127) return status('That position is outside this track’s playable range.');
        const cohort = allBeats().filter(b => b.track === track && cmp(b.at, at) === 0).sort((a, b) => a.voice - b.voice);
        const match = cohort.map(b => ({beat: b, note: b.notes.find(n => n.string === s && n.fret === fret)})).find(pair => pair.note);
        if (audition || fb('mode').value === 'audition') {
          if (pitch > 119) return status('This pitch is outside the current preview engine range (0–119). The score is unchanged.');
          const n = match?.note || current()?.notes.find(n => n.string === s);
          await host.preview({action: 'note', pitch, velocity: n?.velocity, instrument: n?.instrument || t.instrument,
            selection: {...selection(), string: s}});
          return;
        }
        if (!view.editable) return status('Enable editing before changing the score.');
        const w = readWritten();
        if (match) { voice = match.beat.voice; ui('voice').value = voice; }
        choose(at, s); // Resolve an explicit note identity before queuing a cross-voice deletion.
        const target = entryTarget(w);
        return await queueEntry(target, () => {
          if (match) return commit({op: 'note_delete', pattern: target.pattern, beat: match.beat.id, note: match.note.id}, target.revision);
          return writeFret(fret, target);
        });
      } catch (e) { status(`Fretboard: ${e.message || e}`); }
    }
    async function enterPitch(pitch, {audition = false, velocity} = {}) {
      try {
        const refusal = entryRefusal(); if (refusal) return status(refusal);
        const t = spec(), drums = isPercussion(t);
        if (!Number.isInteger(pitch) || pitch < (drums ? 1 : 0) || pitch > (drums ? 100 : 119))
          return status(drums ? 'Enter a drum key from 1 to 100.' : 'Native pitch and preview range is 0–119.');
        if (velocity != null && (!Number.isInteger(velocity) || velocity < 0 || velocity > 127)) return status('Velocity must be from 0 to 127.');
        const cohort = allBeats().filter(b => b.track === track && cmp(b.at, at) === 0).sort((a, b) => a.voice - b.voice);
        const match = cohort.map(beat => ({beat, note: beat.notes.find(n => n.pitch === pitch)})).find(pair => pair.note);
        if (audition) return await host.preview({action: 'note', pitch, velocity: velocity ?? match?.note.velocity,
          instrument: match?.note.instrument ?? t.instrument, selection: selection()});
        if (!view.editable) return status('Enable editing before changing the score.');
        if (!match && beats().some(b => b.notes.length && cmp(b.at, at) < 0 && cmp(at, add(b.at, duration(b.written))) < 0))
          return status('This caret is inside an authored sounding note; select its start before entering a note.');
        const w = readWritten();
        let s = match?.note.string, fret;
        if (!match) {
          const used = new Set(cohort.flatMap(b => b.notes.map(n => n.string)));
          s = t.tuning.findIndex((open, i) => !used.has(i + 1) && (drums || pitch >= open + (t.capo || 0))) + 1;
          if (!s) return status('No unused string or lane can hold this note at the selected onset.');
          fret = drums ? pitch : pitch - t.tuning[s - 1] - (t.capo || 0);
          if (!drums && fret > (t.max_fret ?? 29)) return status('The first available string exceeds its fret limit.');
        }
        if (match) { voice = match.beat.voice; ui('voice').value = voice; }
        choose(at, s);
        const target = entryTarget(w);
        return await queueEntry(target, () => {
          if (match) return commit({op: 'note_delete', pattern: target.pattern, beat: match.beat.id, note: match.note.id}, target.revision);
          const b = current(), note = {id: uid('note'), pitch, string: s, fret, ...(velocity == null ? {} : {velocity})};
          if (b && b.written.value === w.value && (b.written.dots || 0) === w.dots &&
            JSON.stringify(b.written.tuplet || [1,1]) === JSON.stringify(w.tuplet))
            return commit({op: 'note_set', pattern: target.pattern, beat: b.id, note}, target.revision);
          const beat = b ? authoredBeat(b) : {id: uid('beat'), track: target.track, voice: target.voice, at: target.at, notes: []};
          if (!b || cmp(duration(b.written), duration(w)) !== 0) delete beat.duration_source;
          beat.written = w; beat.notes.push(note);
          return commit({action: 'place', occurrence: target.occurrence, beat,
            ...(b && target.fit ? {fit: 'tg_insert'} : {})}, target.revision);
        });
      } catch (e) { status(`Piano: ${e.message || e}`); }
    }
    async function enterMatrix(pitch, position) {
      try {
        const refusal = entryRefusal(); if (refusal) return status(refusal);
        if (!view.editable) return status('Enable editing before changing the score.');
        const target = entryTarget();
        const free = ui('free-edit').checked;
        return await queueEntry(target, () => commit({action: 'matrix_entry', occurrence: target.occurrence,
          track: target.track, voice: target.voice, at: position, pitch, written: target.written, fit: target.fit, free}, target.revision,
          result => { if (result.audition?.length && view?.song === target.song && view?.revision === result.revision && !host.isPlaying?.() && !playhead)
            Promise.resolve(host.preview({notes: result.audition}))
            .catch(e => status(`Matrix audition: ${e.message || e}`)); }));
      } catch (e) { status(`Matrix: ${e.message || e}`); }
    }
    function drawPiano() {
      if (!piano.open || destroyed) return;
      const t = spec(), drums = isPercussion(t), playing = !!(playhead || host.isPlaying?.());
      const cohort = playing ? (boardPlayback || []).filter(b => b.track === track) : view ? allBeats().filter(b => b.track === track && cmp(b.at, at) === 0) : [];
      const key = JSON.stringify([t, cohort, boardPrefs.root, boardPrefs.scale, track, voice, at, playing, busy, boardPending,
        !!rawSelected, ambiguousSelection, view?.editable, view?.native, pk('mode').value]);
      if (key === pianoKey) return; pianoKey = key;
      const focused = pianoKeys.contains(document.activeElement);
      pianoKeys.replaceChildren(); pianoKeys.classList.toggle('drums', drums);
      pk('context').textContent = t ? `${t.name || track} · Voice ${voice + 1} · ${at.join('/')} · ${drums ? 'Drum keys 1–100' : 'Concert pitch includes capo'}` : 'Choose a native track.';
      if (!t || !view?.native) return;
      const blocked = !!entryRefusal() || (!view.editable && pk('mode').value !== 'audition');
      const mask = scaleCatalogue[boardPrefs.scale]?.[1] || 0, fifths = scaleFifths(mask, boardPrefs.root);
      let white = 0;
      for (let pitch = drums ? 1 : 0; pitch <= (drums ? 100 : 119); pitch++) {
        const sharp = [1,3,6,8,10].includes(pitch % 12), label = spellingText(keySpelling(pitch, fifths));
        const name = drums ? `Drum key ${pitch}` : `${label} (${pitch})`;
        const button = text('button', drums ? String(pitch) : `${label}${pitch % 12 === 0 ? pitch / 12 : ''}`);
        button.type = 'button'; button.dataset.pianoPitch = pitch; button.title = name; button.setAttribute('aria-label', name);
        button.tabIndex = pitch === pianoFocus ? 0 : -1; button.setAttribute('aria-disabled', String(blocked));
        const voices = cohort.filter(b => b.notes.some(n => n.pitch === pitch)).map(b => b.voice);
        button.dataset.voices = voices.join(','); button.setAttribute('aria-pressed', String(!!voices.length));
        button.dataset.scale = String(!drums && scaleHas(mask, rootPitch(boardPrefs.root), pitch));
        if (!drums) { button.className = sharp ? 'sharp' : 'natural'; button.style.left = (sharp ? white * 38 - 12 : white++ * 38) + 'px'; }
        pianoKeys.append(button);
      }
      pianoKeys.style.width = drums ? '' : white * 38 + 'px';
      if (focused) pianoKeys.querySelector('[tabindex="0"]')?.focus({preventScroll: true});
    }
    function drawFretboard() {
      if (!board.open || destroyed) return;
      const t = spec(), drums = isPercussion(t), playing = !!(playhead || host.isPlaying?.());
      const cohort = playing ? (boardPlayback || []).filter(b => b.track === track) : view ? allBeats().filter(b => b.track === track && cmp(b.at, at) === 0) : [];
      const key = JSON.stringify([t, cohort, boardPrefs, fb('mode').value, track, voice, at, string, playing, busy, boardPending, !!rawSelected, ambiguousSelection, view?.native, view?.editable]);
      if (key === boardKey) return; boardKey = key;
      const focused = boardSvg.contains(document.activeElement) ? document.activeElement.dataset : null;
      const focusString = Number(focused?.fbString || string), focusFret = Number(focused?.fbFret || (view && current()?.notes.find(n => n.string === string)?.fret) || 0);
      boardSvg.replaceChildren();
      for (const name of ['root', 'scale', 'noteText', 'scaleText']) fb(name).disabled = !t || drums;
      if (!t || drums || !view?.native) {
        fb('context').textContent = drums ? 'Percussion uses the native lane/key controls; pitched scales and frets do not apply.' : 'Set up a native pitched track to use the fretboard.';
        return;
      }
      fb('context').textContent = `${t.name || track} · tuning ${isPercussion(t) ? 'drum lanes' : t.tuning.map(pitchName).join(' ')} · capo ${t.capo || 0} · ${playing ? 'Playing (entry paused)' : `Voice ${voice + 1} · ${occurrence()} · ${at.join('/')}`}`;
      const max = t.max_fret ?? 29, step = 48, margin = 56, spacing = boardPrefs.spacing, height = 48 + spacing * t.tuning.length;
      const width = margin + step * (max + 1), x = f => margin + step * ((boardPrefs.direction === 'left' ? max - f : f) + .5);
      const contrast = color => color.slice(1).match(/../g).reduce((sum, value) => sum + parseInt(value, 16), 0) > 384 ? '#000000' : '#ffffff';
      const element = (tag, attrs, value, parent = boardSvg) => {
        const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
        for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
        if (value != null) el.textContent = value; parent.append(el); return el;
      };
      boardSvg.setAttribute('viewBox', `0 0 ${width} ${height}`); boardSvg.style.width = width + 'px'; boardSvg.style.height = height + 'px';
      boardSvg.style.background = boardPrefs.background; boardSvg.style.fontFamily = boardPrefs.font;
      boardSvg.style.fontSize = boardPrefs.size + 'px'; boardSvg.style.fontWeight = boardPrefs.bold ? 'bold' : 'normal';
      boardSvg.style.fontStyle = boardPrefs.italic ? 'italic' : 'normal';
      const mask = scaleCatalogue[boardPrefs.scale]?.[1] || 0, rootPitchClass = rootPitch(boardPrefs.root), fifths = scaleFifths(mask, boardPrefs.root);
      for (let f = 0; f <= max; f++) {
        element('text', {x: x(f), y: 18, fill: boardPrefs.strings, 'text-anchor': 'middle'}, f);
        if (f) element('line', {x1: x(f) + (boardPrefs.direction === 'left' ? -step/2 : step/2),
          x2: x(f) + (boardPrefs.direction === 'left' ? -step/2 : step/2), y1: 24, y2: height - 12, stroke: boardPrefs.strings});
        if ([0, 3, 5, 7, 9].includes(f % 12) && f > 0)
          element('text', {x: x(f), y: height - 3, fill: boardPrefs.points, 'text-anchor': 'middle'}, f % 12 === 0 ? '••' : '•');
      }
      t.tuning.forEach((open, i) => {
        const y = 32 + spacing * (i + .5), s = i + 1;
        element('text', {x: 4, y: y + 4, fill: boardPrefs.strings}, s);
        element('line', {x1: margin, x2: width, y1: y, y2: y, stroke: boardPrefs.strings});
        for (let f = 0; f <= max; f++) {
          const pitch = open + (t.capo || 0) + f, matches = cohort.flatMap(b => b.notes.filter(n => n.string === s && n.fret === f).map(n => ({b, n})));
          const selected = matches.find(m => m.b.voice === voice) || matches[0], inScale = scaleHas(mask, rootPitchClass, pitch);
          const enabled = pitch >= 0 && pitch <= 127, active = !playing && s === string && selected?.b.voice === voice;
          const name = spellingText(selected?.n.spelling || keySpelling(pitch, selected ? t.key?.fifths : fifths));
          const g = element('g', {'data-fb-string': s, 'data-fb-fret': f, 'data-pitch': pitch, 'data-scale': inScale,
            'data-voices': matches.map(m => m.b.voice).join(','), role: 'button', tabindex: s === focusString && f === focusFret ? 0 : -1,
            'aria-label': `String ${s}, fret ${f}, ${name}, pitch ${pitch}${matches.length ? ', voice ' + matches.map(m => m.b.voice + 1).join(' and ') : ''}`,
            'aria-pressed': !!selected, 'aria-disabled': !enabled || !!boardRefusal() || fb('mode').value === 'edit' && !view.editable});
          element('rect', {x: x(f) - step/2 + 1, y: y - spacing/2, width: step-2, height: spacing, fill: 'transparent',
            stroke: active ? '#69ceb4' : 'transparent', 'stroke-width': 2}, null, g);
          if (selected || inScale) {
            const color = selected ? boardPrefs.notes : boardPrefs.scaleColor;
            element('ellipse', {cx: x(f), cy: y, rx: Math.min(21, spacing/2-1), ry: spacing/2-2, fill: color,
              stroke: selected && inScale ? boardPrefs.scaleColor : color, 'stroke-width': selected && inScale ? 3 : 1}, null, g);
            if (selected ? boardPrefs.noteText : boardPrefs.scaleText)
              element('text', {x: x(f), y: y + boardPrefs.size * .35, fill: contrast(color), 'text-anchor': 'middle'}, name, g);
          }
          element('title', {}, `String ${s} · fret ${f} · concert ${name} (${pitch})`, g);
        }
      });
      if (focused) boardSvg.querySelector(`[data-fb-string="${focusString}"][data-fb-fret="${focusFret}"]`)?.focus({preventScroll: true});
    }
    function commandControls() {
      for (const action of ['cut', 'repeat']) root.querySelector(`[data-action="${action}"]`).disabled =
        busy || !!rawSelected || !view?.editable || !view?.native || !selectedBeats.size && !rangeSelection.length || !!host.isPlaying?.();
    }
    function durationReport(result) {
      const count = result.removed_ties?.length || 0, kept = result.kept_durations?.length || 0,
        consumed = result.consumed_rests?.length || 0;
      return (result.outcomes?.includes('shifted') ? ' Fit moved or resized following beats.' : '') +
        (kept ? ` ${kept} ${kept === 1 ? 'beat kept' : 'beats kept'} at the previous duration; not enough room.` : '') +
        (consumed ? ` ${consumed} selected ${consumed === 1 ? 'rest absorbed' : 'rests absorbed'}.` : '') +
        (count ? ` ${count} ${count === 1 ? 'tie removed' : 'ties removed'}; separated notes play normally.` : '');
    }
    function commit(edit, revision = view?.revision, accepted = null) {
      if (crossRange() && !['set_stem', 'retune', 'transpose', 'transfer_voice', 'track_add', 'track_clone', 'track_remove', 'track_move'].includes(edit.action) && !MEASURE_ACTIONS.includes(edit.action) && !['beats_paste','metadata_set'].includes(edit.op)) { status('Choose one beat before individual-note edits; phrase and measure commands keep the current range.'); return Promise.resolve(false); }
      if (ambiguousSelection) { status('Choose a source note in Pattern, ROLL or TAB before editing an overlapping voice.'); return Promise.resolve(false); }
      if (busy) { status('Wait for the current edit to finish.'); return Promise.resolve(false); }
      if (!view?.editable) { status('Enable editing before changing the score.'); return Promise.resolve(false); }
      const placement = edit.action === 'place', target = entryTarget(placement ? edit.beat.written : written),
        command = placement || ['matrix_entry', 'set_stem', 'set_duration', 'remove_unused_voice', 'clean_beat', 'retune', 'transpose', 'insert_rest', 'move_beats', 'transfer_voice', 'track_add', 'track_clone', 'track_remove', 'track_move', ...MEASURE_ACTIONS].includes(edit.action);
      if (ui('independent').checked && (['matrix_entry','set_stem','place','set_duration','remove_unused_voice','clean_beat','insert_rest','move_beats','transfer_voice',...MEASURE_ACTIONS].includes(edit.action) || edit.op === 'beats_paste')) edit = {...edit, independent:true};
      busy = true; controls(); status('Saving…');
      saving = (async () => {
        try {
          const result = await (command ? host.command(edit, revision) : host.commit(edit, revision));
          if (result?.error) throw new Error(result.error);
          if (result?.score) update(result);
          if (result?.track && edit.action?.startsWith('track_') && view.score.tracks[result.track]) selectTrack(result.track, true);
          if (placement && result.selection && sameEntryPosition(target)) {
            const selected = result.selection;
            const actual = allBeats().find(b => selected.beats.includes(b.id) && b.track === selected.track && b.voice === selected.voice);
            if (selected.occurrence === target.occurrence && actual) {
              const note = actual.notes.find(n => selected.notes.includes(n.id) && n.string === target.string);
              track = selected.track; voice = selected.voice;
              choose(selected.at, note?.string ?? target.string, target.chord);
              if (result.fit) written = clone(result.fit.applied);
            }
          }
          // A completed edit may select its result only while the user is still
          // at its submission position (as with ordinary note placement above).
          if ((['matrix_entry', 'set_duration'].includes(edit.action) || edit.op === 'beats_paste') && result.selection && sameEntryPosition(target)) {
            const selected = result.selection, selectedString = string, selectedChord = chosen === 'chord';
            const order = view.score.order_ids.indexOf(selected.occurrence);
            if (order >= 0 && order !== view.order) update({...view, order, pattern: String(view.orders[order])});
            track = selected.track; voice = selected.voice;
            choose(selected.at, selected.string ?? selectedString, selectedChord, false);
            rangeSelection = clone(selected.range || []);
            selectedBeats = new Set(selected.beats);
            if (edit.op === 'beats_paste') selectionAnchor = {occurrence: selected.occurrence, at: [...selected.at]};
            selectedNotes = new Map(allBeats().filter(b => selectedBeats.has(b.id))
              .map(b => [b.id, new Set(b.notes.map(n => n.id))]));
            const actual = current();
            if (actual) written = clone(actual.written);
            navigationEcho = {...selection(), song: view.song, revision: view.revision};
            notifying = true; try { host.select(selection()); } finally { notifying = false; }
            drawGrid(); engrave(); markEditCaret();
          }
          accepted?.(result);
          if (result.matrix === 'absent_voice') { status('Audition only: no containing beat in this voice; the score is unchanged.'); return true; }
          if (['retune', 'transpose'].includes(edit.action)) { status(changeReport(edit.action, result)); return true; }
          if (MEASURE_ACTIONS.includes(edit.action)) { status(result.report || 'Saved.'); return true; }
          if (edit.action === 'move_beats') { status(`Moved ${result.moved} beat${result.moved === 1 ? '' : 's'}${result.removed.length ? `; removed ${result.removed.length}` : ''}.` + durationReport(result)); return true; }
          if (edit.op === 'beats_paste' && result.selection) { status('Pasted phrase selected; one Undo restores it.'); return true; }
          if (edit.action === 'insert_rest' && result.overfull) { status('Rest inserted; the measure is now overfull (free edit).'); return true; }
          if (edit.action === 'insert_rest') { status(result.dropped?.length ? `Rest inserted; ${result.dropped.length} trailing rest${result.dropped.length === 1 ? '' : 's'} dropped.` : 'Rest inserted.'); return true; }
          if (edit.action === 'clean_beat') { status(`Cleaned ${result.cleaned.length} beat${result.cleaned.length === 1 ? '' : 's'}.`); return true; }
          if (edit.action === 'remove_unused_voice') { status(result.removed?.length ?
            `Removed ${result.removed.length} rest${result.removed.length === 1 ? '' : 's'} of voice ${result.voice + 1}.` : 'No unused voice to remove here.'); return true; }
          if (result.outcomes) { status((result.outcomes.every(o => o === 'unchanged') ? 'Duration unchanged.' :
            'Selected rhythm updated; one Undo restores it.') + durationReport(result)); return true; }
          status((result.fit ? ({
            exact: 'Duration applied.',
            shifted: 'Duration applied; following notes moved or resized.',
            old_duration: 'Note added at the previous duration.',
            unchanged: 'Duration unchanged.'
          }[result.fit.outcome] || 'Saved.') : 'Saved.') + durationReport(result)); return true;
        } catch (e) { lastDigit = null; status(`Edit refused: ${e.message || e}`); return false; }
        finally { busy = false; if (!destroyed) controls(); }
      })();
      return saving;
    }
    function readWritten() {
      const w = {value: +ui('duration').value, dots: +ui('dots').value, tuplet: [+ui('tuple-n').value, +ui('tuple-d').value]};
      if (!w.tuplet.every(n => Number.isInteger(n) && n >= 1 && n <= 32)) throw new Error('Tuplet values must be integers from 1 to 32.');
      written = w; return clone(w);
    }
    function writeFret(fret, target, accepted = null) {
      if (destroyed || target.song !== view?.song || target.pattern !== view?.pattern || target.order !== view?.order) return;
      const t = view.score?.tracks[target.track]; if (!t) return;
      const b = allBeats().find(b => b.track === target.track && b.voice === target.voice && cmp(b.at, target.at) === 0);
      const old = b?.notes?.find(n => n.string === target.string);
      const n = {...(old || {}), id: old?.id || uid('note'), string: target.string, fret,
        pitch: isPercussion(t) ? fret : t.tuning[target.string - 1] + (t.capo || 0) + fret};
      const receipt = result => accepted?.({revision: result.revision, beat: result.selection?.beats[0] || b?.id, note: n.id});
      if (b) return commit({op: 'note_set', pattern: target.pattern, beat: b.id, note: n}, target.revision, receipt);
      const beat = {id: uid('beat'), track: target.track, voice: target.voice, at: target.at, written: target.written, notes: [n]};
      return commit(view.native ? {action: 'place', occurrence: target.occurrence, beat} :
        {op: 'beat_set', pattern: target.pattern, beat}, target.revision, receipt);
    }
    function queueFret(fret) {
      if (view?.native) {
        if ((busy && !fretJob?.pending) || boardPending || host.isPlaying?.() || playhead ||
          !view.editable || rawSelected || ambiguousSelection || document.querySelector('dialog[open], .modal.on')) {
          lastDigit = null; return status('Wait for editing to be available before entering a fret.');
        }
        const target = {...entryTarget(), note: current()?.notes.find(n => n.string === string)?.id || null, epoch: fretEpoch};
        const previous = fretJob?.pending && fretJob.target.epoch === target.epoch ? fretJob : null;
        const job = {target, pending: true, receipt: null};
        fretJob = job;
        fretChain = fretChain.then(async () => {
          await saving;
          const prior = previous?.receipt;
          const follows = previous && prior && [previous.target.revision, previous.inputRevision, prior.revision].includes(target.revision);
          const expected = follows ? prior : target;
          if ((previous && !follows) || fretEpoch !== target.epoch || !sameEntryPosition(target) ||
            view.revision !== expected.revision || (current()?.id || null) !== expected.beat ||
            (current()?.notes.find(n => n.string === string)?.id || null) !== expected.note ||
            !view.editable || host.isPlaying?.() || playhead || document.querySelector('dialog[open], .modal.on')) {
            lastDigit = null; return status('The score or selection changed before fret entry; queued digits were cancelled.');
          }
          job.inputRevision = expected.revision;
          return writeFret(fret, {...target, revision: expected.revision}, receipt => {
            // Only this response can advance the next digit's expected revision/identity.
            if (fretEpoch === target.epoch && sameEntryPosition(target) && view.revision === receipt.revision &&
              current()?.id === receipt.beat && current()?.notes.some(n => n.id === receipt.note && n.string === target.string))
              job.receipt = receipt;
          });
        }).catch(e => { lastDigit = null; status(`Edit refused: ${e.message || e}`); })
          .finally(() => { job.pending = false; });
        return fretChain;
      }
      const target = {song: view?.song, pattern: view.pattern, order: view.order, track, voice, at: [...at], string, written: readWritten()};
      fretChain = fretChain.then(async () => { await saving; return writeFret(fret, target); }).catch(e => { lastDigit = null; status(`Edit refused: ${e.message || e}`); });
      return fretChain;
    }
    function enterFret() {
      if (rawSelected) return status('This is an existing Pattern note. Adopt it explicitly before editing notation.');
      if (!spec()) return status('Set up a track first.');
      const value = pending || ui('fret').value, fret = Number(value);
      const drums = isPercussion(spec()), max = drums ? 100 : spec().max_fret ?? 29, min = drums ? 1 : 0;
      if (!value || !Number.isInteger(fret) || fret < min || fret > max) return status(`Enter a ${drums ? 'drum key' : 'fret'} from ${min} to ${max}.`);
      pending = ''; lastDigit = null; return queueFret(fret);
    }
    function digitFret(digit) {
      if (rawSelected) return status('This is an existing Pattern note. Adopt it explicitly before editing notation.');
      if (!spec()) return status('Set up a track first.');
      if (!view?.editable) return status('Enable editing before changing the score.');
      if (view.native && fretJob && !fretJob.pending && fretJob.receipt?.revision !== view.revision) lastDigit = null;
      const key = entryKey(), time = Date.now(), previous = lastDigit;
      if (isPercussion(spec())) {
        const value = previous?.key === key && time < previous.time + 1000 ? previous.fret * 10 + digit : digit;
        if (value < 1 || value > 100) { lastDigit = null; return status('Enter a drum key from 1 to 100.'); }
        lastDigit = {key, time, fret: value}; pending = ''; ui('fret').value = value;
        return queueFret(value);
      }
      let fret = digit;
      // TuxGuitar 2.1.0 TGSetNoteFretNumberAction: combine only a prior 1–9,
      // strictly inside 1000ms at the same start/string, if the result fits.
      if (previous?.key === key && previous.fret > 0 && previous.fret < 10 && time < previous.time + 1000) {
        const combined = previous.fret * 10 + digit;
        if (combined <= (spec().max_fret ?? 29)) fret = combined;
      }
      lastDigit = {key, time, fret}; pending = ''; ui('fret').value = fret;
      return queueFret(fret);
    }
    async function changeNote(delta, shiftString) {
      if (noteRange()) return commandBeats(shiftString ? 'shift_strings' : 'shift_pitch', {direction: delta});
      if (isPercussion(spec()) && !shiftString) return percussionRefusal();
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      if (busy) return status('Wait for the current edit to finish.');
      const b = current(), n = b?.notes.find(n => n.string === string);
      if (!n || chosen === 'chord') return status('Select one note on a string first.');
      lastDigit = null;
      const nextString = string + (shiftString ? delta : 0), tuning = spec().tuning, max = isPercussion(spec()) ? 100 : spec().max_fret ?? 29;
      if (nextString < 1 || nextString > tuning.length) return status(`There is no adjacent ${isPercussion(spec()) ? 'lane' : 'string'} in that direction.`);
      const fret = shiftString ? n.pitch - tuning[nextString - 1] - (spec().capo || 0) : n.fret + delta;
      if (fret < 0 || fret > max) return status('That change is outside this string’s fret range.');
      if (shiftString && b.notes.some(other => other.id !== n.id && other.string === nextString)) return status(isPercussion(spec()) ?
        'The adjacent lane already has a hit at this beat.' : 'The adjacent string already has a note in this chord.');
      const patch = {id: n.id, string: nextString, fret};
      if (shiftString) patch.pitch = n.pitch;
      const target = entryTarget(written);
      const saved = await commit({op: 'note_set', pattern: view.pattern, beat: b.id, note: patch});
      if (saved && shiftString && sameEntryPosition(target)) choose(b.at, nextString);
    }
    function toggleTechnique(flag) {
      if (noteRange() && rangeArticulations.includes(flag)) return commandBeats('set_expression',
        {changes: {[flag]: ui('range-articulation').value === 'set'}});
      if (busy || rawSelected || !view?.native) return;
      const b = current(), selected = b?.notes.filter(n => chosen === 'chord' || selectedNotes.get(b.id)?.has(n.id)) || [];
      if (!selected.length) return status('Select a note or chord first.');
      const enabled = !selected.every(n => n[flag]);
      return commit({op: 'notes_set', pattern: view.pattern,
        notes: selected.map(n => ({beat: b.id, note: {id: n.id, [flag]: enabled}}))});
    }
    function applyTapSlapPop() {
      const b = current(), notes = noteRange() ? rangeNotes() : b?.notes.filter(n => chosen === 'chord' || selectedNotes.get(b.id)?.has(n.id)) || [];
      if (busy || rawSelected || !view?.native || !notes.length) return;
      const kind = ui('tap-slap-pop').value;
      if (kind === 'mixed') return status('Choose None, Tap, Slap or Pop for this mixed selection.');
      if (noteRange()) return commandBeats('set_expression',
        {changes: Object.fromEntries(tapSlapPop.map(([flag]) => [flag, flag === kind]))});
      return commit({op: 'notes_set', pattern: view.pattern, notes: notes.map(n => ({beat: b.id,
        note: {id: n.id, ...Object.fromEntries(tapSlapPop.map(([flag]) => [flag, flag === kind]))}}))});
    }
    function applyHarmonic() {
      const b = current(), notes = noteRange() ? rangeNotes() : b?.notes.filter(n => chosen === 'chord' || selectedNotes.get(b.id)?.has(n.id)) || [];
      if (busy || rawSelected || !view?.native || !notes.length) return;
      const type = ui('harmonic-type').value;
      if (type === 'mixed') return status('Choose a harmonic type for this mixed chord.');
      if (type && notes.some(n => n.velocity == null)) return status('Assign an explicit velocity before applying harmonics.');
      const harmonic = type ? {type, data: type === 'natural' ? 0 : Number(ui('harmonic-data').value)} : null;
      if (noteRange()) return commandBeats('set_expression', {changes: {harmonic}});
      return commit({op: 'notes_set', pattern: view.pattern,
        notes: notes.map(n => ({beat: b.id, note: {id: n.id, harmonic}}))});
    }
    function graceControls() {
      for (const field of ['fret', 'value', 'velocity', 'timing', 'transition', 'dead'])
        ui(`grace-${field}`).disabled = ui('grace-kind').disabled || ui('grace-kind').value !== 'grace';
    }
    function applyGrace() {
      const b = current(), notes = noteRange() ? rangeNotes() : b?.notes.filter(n => chosen === 'chord' || selectedNotes.get(b.id)?.has(n.id)) || [];
      if (busy || rawSelected || !view?.native || !notes.length) return;
      const kind = ui('grace-kind').value;
      if (kind === 'mixed') return status('Choose Grace note or None for this mixed chord.');
      let grace = null;
      if (kind) {
        const fret = Number(ui('grace-fret').value), velocity = Number(ui('grace-velocity').value);
        if (!ui('grace-fret').value.trim() || !ui('grace-fret').validity.valid || !Number.isInteger(fret) ||
            fret < (isPercussion(spec()) ? 1 : 0) || fret > (isPercussion(spec()) ? 100 : spec()?.max_fret ?? 29))
          return status(isPercussion(spec()) ? 'Choose a grace drum key from 1 to 100.' : 'Choose a grace fret within this track’s fret range.');
        if (!ui('grace-velocity').value.trim() || !ui('grace-velocity').validity.valid ||
            !Number.isInteger(velocity) || velocity < 0 || velocity > 127) return status('Grace velocity must be an integer from 0 to 127.');
        if (notes.some(n => n.string == null)) return status('Grace needs a resolved string for each selected note.');
        grace = {fret, value: Number(ui('grace-value').value), velocity,
          transition: ui('grace-transition').value, on_beat: ui('grace-timing').value === 'on', dead: ui('grace-dead').checked};
      }
      if (noteRange()) return commandBeats('set_expression', {changes: {grace}});
      return commit({op: 'notes_set', pattern: view.pattern,
        notes: notes.map(n => ({beat: b.id, note: {id: n.id, grace}}))});
    }
    function repetitionRates(type, selected) {
      const values = type === 'trill' ? [4, 8, 16, 32, 64] : type === 'tremolo_picking' ? [8, 16, 32] : [];
      ui('repetition-value').replaceChildren(...values.map(value => {
        const option = text('option', `1/${value}`); option.value = value; return option;
      }));
      ui('repetition-value').value = selected == null ? '16' : String(selected);
    }
    function applyRepetition() {
      const b = current(), notes = noteRange() ? rangeNotes() : b?.notes.filter(n => chosen === 'chord' || selectedNotes.get(b.id)?.has(n.id)) || [];
      if (busy || rawSelected || !view?.native || !notes.length) return;
      const type = ui('repetition-type').value;
      if (type === 'trill' && isPercussion(spec())) return percussionRefusal();
      if (type === 'mixed') return status('Choose a repetition type for this mixed chord.');
      if (type && notes.some(n => n.velocity == null)) return status('Assign an explicit velocity before applying trill or tremolo picking.');
      const value = Number(ui('repetition-value').value), fret = Number(ui('trill-fret').value);
      if (type && !(type === 'trill' ? [4, 8, 16, 32, 64] : [8, 16, 32]).includes(value))
        return status('Choose a repetition rate for the selected notes.');
      if (type === 'trill' && (!ui('trill-fret').value.trim() || !ui('trill-fret').validity.valid ||
          !Number.isInteger(fret) || fret < 0 || fret > (spec()?.max_fret ?? 29)))
        return status('Choose an alternate fret within this track’s fret range.');
      if (type === 'trill' && notes.some(n => n.string == null))
        return status('Trill needs a resolved string for each selected note.');
      if (noteRange()) return commandBeats('set_expression', {changes: {
        trill: type === 'trill' ? {fret, value} : null,
        tremolo_picking: type === 'tremolo_picking' ? {value} : null}});
      return commit({op: 'notes_set', pattern: view.pattern, notes: notes.map(n => ({beat: b.id,
        note: {id: n.id, trill: type === 'trill' ? {fret, value} : null,
          tremolo_picking: type === 'tremolo_picking' ? {value} : null}}))});
    }
    function applyVelocity() {
      const b = current(), notes = noteRange() ? rangeNotes() : b?.notes.filter(n => chosen === 'chord' || selectedNotes.get(b.id)?.has(n.id)) || [];
      if (busy || rawSelected || !view?.native || !notes.length) return;
      const input = ui('velocity').value.trim(), velocity = input === '' ? null : Number(input);
      if (!ui('velocity').validity.valid || velocity !== null && (!Number.isInteger(velocity) || velocity < 0 || velocity > 127))
        return status('Velocity must be an integer from 0 to 127, or blank for instrument default.');
      if (!input && ui('velocity').placeholder === 'mixed' && ui('dynamics').value === 'custom')
        return status(`Choose a dynamic, enter a velocity, or select Instrument default for this mixed ${noteRange() ? 'selection' : 'chord'}.`);
      if (noteRange()) return commandBeats('set_expression', {changes: {velocity}});
      return commit({op: 'notes_set', pattern: view.pattern,
        notes: notes.map(n => ({beat: b.id, note: {id: n.id, velocity}}))});
    }
    function readChordDiagram() {
      const name = ui('chord-name').value, first_fret = Number(ui('chord-first').value), max = chordTarget.maxFret;
      if ([...name].length > 4096) throw new Error('Chord name must be at most 4096 characters.');
      if (!ui('chord-first').value.trim() || !Number.isInteger(first_fret) || first_fret < 0 || first_fret > max)
        throw new Error(`First fret must be an integer from 0 to ${max}.`);
      const frets = [...ui('chord-strings').querySelectorAll('input')].sort((a, b) => +a.dataset.chordString - +b.dataset.chordString).map(input => {
        const value = input.value.trim();
        if (!/^(?:x|-1|0|[1-9]\d*)$/i.test(value)) throw new Error(`String ${input.dataset.chordString}: enter X, 0, or an absolute fret.`);
        const fret = /^x$/i.test(value) ? -1 : Number(value);
        if (fret > max) throw new Error(`String ${input.dataset.chordString}: maximum fret is ${max}.`);
        return fret;
      });
      const chord = {name, first_fret, frets}, first = chordFirstFret(chord);
      if (frets.some(f => f > 0 && (f < first || f > first + 4))) throw new Error(`Positive frets must fit the five-fret window ${first}–${first + 4}.`);
      return chord;
    }
    function lyricsControls() {
      root.querySelector('[data-action="lyrics"]').disabled = busy || !spec() || !view?.native;
      const disabled = busy || !lyricsTarget || !view?.editable || !view?.native || !!host.isPlaying?.();
      ui('lyrics-apply').disabled = disabled;
      root.querySelector('[data-action="lyrics-remove"]').disabled = disabled;
      ui('lyrics-map').textContent = (view?.lyrics?.errors || []).filter(e => e.track === (lyricsTarget?.track || track))
        .map(e => e.message).join(' · ');
    }
    function openLyrics() {
      if (busy || !spec() || !view?.native) return;
      const saved = spec().lyrics;
      lyricsTarget = {song: view.song, revision: view.revision, track, rawText: saved?.text ?? '', textEdited: false};
      ui('lyrics-target').textContent = `Lyrics · ${spec().name || track} (${track})`;
      ui('lyrics-from').value = saved?.from_measure ?? 1;
      ui('lyrics-text').value = lyricsTarget.rawText;
      ui('lyrics-status').textContent = '';
      root.querySelector('.vt-tab-lyrics').hidden = false; lyricsControls(); ui('lyrics-text').focus();
    }
    function closeLyrics() { closePanel('lyrics'); }
    async function saveLyrics(remove = false) {
      if (!lyricsTarget || busy) return;
      const target = lyricsTarget;
      if (target.song !== view.song || target.revision !== view.revision || target.track !== track)
        return ui('lyrics-status').textContent = 'The song, track or revision changed. Reopen Lyrics before saving.';
      if (host.isPlaying?.()) return ui('lyrics-status').textContent = 'Stop playback before saving or removing lyrics.';
      try {
        const value = clone(view.score.tracks[target.track]);
        if (remove) delete value.lyrics;
        else {
          const input = ui('lyrics-from').value.trim(), from_measure = Number(input);
          if (!input || !Number.isInteger(from_measure) || from_measure < 1 || from_measure > 2147483647)
            throw new Error('Starting measure must be an integer from 1 to 2147483647.');
          const raw = target.textEdited ? ui('lyrics-text').value : target.rawText;
          if ([...raw].length > 65536) throw new Error('Lyrics must be at most 65536 characters; no text was truncated.');
          value.lyrics = {from_measure, text: raw};
        }
        const saved = await commit({op: 'track_set', track: target.track, value});
        if (!destroyed && lyricsTarget === target) {
          if (saved) closeLyrics();
          else ui('lyrics-status').textContent = root.querySelector('.vt-tab-status').textContent;
        }
      } catch (e) { if (!destroyed && lyricsTarget === target) ui('lyrics-status').textContent = e.message; }
    }
    listen(ui('lyrics-text'), 'input', () => { if (lyricsTarget) lyricsTarget.textEdited = true; });
    listen(root.querySelector('.vt-tab-lyrics'), 'submit', e => { e.preventDefault(); saveLyrics(); });
    function drawChordDiagram() {
      const preview = ui('chord-preview'); preview.replaceChildren();
      ui('chord-notes-preview').textContent = ''; ui('chord-ties-preview').textContent = '';
      try {
        const chord = readChordDiagram(), first = chordFirstFret(chord);
        drawChordShape(preview, chord);
        ui('chord-status').textContent = chord.first_fret ? '' : `Automatic display starts at fret ${first}; the saved first fret remains 0.`;
        const impact = chordNoteImpact(view, chordTarget.pattern, chordTarget.beat, chord), b = impact.beat;
        const w = b.written, tuple = w.tuplet || [1, 1], trackSpec = view.score.tracks[b.track];
        const other = impact.affected.map(n => `voice ${n.voice + 1} string ${n.string} (${n.id})`).join(', ') || 'none';
        const action = impact.noOp ? 'The whole beat already rests: all-X replacement makes no change.' :
          `Replaces all ${b.notes.length} notes and their effects in this voice with ${impact.strings.length} fresh notes from the frets${impact.strings.length ? '' : ' (clears the voice)'}.`;
        ui('chord-notes-preview').textContent = `Target: ${trackSpec.name || b.track}, voice ${b.voice + 1} · ` +
          `preserve duration 1/${w.value}${w.dots ? `, ${w.dots} dot(s)` : ''}${tuple[0] !== tuple[1] ? `, tuplet ${tuple.join(':')}` : ''} · ` +
          `track instrument ${trackSpec.instrument} · pattern ${chordTarget.pattern}: ${impact.uses} affected occurrence(s). ` +
          `${action} Other-voice notes removed at this onset: ${other}. Entry velocity applies to every new note; 0 means silent attacks. ` +
          'Per-note instrument overrides are replaced by the track instrument.' +
          (impact.unresolved.length ? ` Cannot resolve other-voice strings: ${impact.unresolved.map(n => n.id).join(', ')}; replacement will be refused.` : '');
        ui('chord-ties-preview').textContent = impact.ties.length ?
          `${impact.ties.length} affected tie(s): ${impact.ties.map(t => `${t.from.occurrence}/${t.from.note} → ${t.to.occurrence}/${t.to.note}`).join('; ')}. Replacement refuses unless Remove ties is checked.` :
          'No ties touch the replaced notes.';
      } catch (e) { ui('chord-status').textContent = e.message; }
    }
    function openChordDiagram() {
      const b = current(); if (!b || busy || rawSelected || !view?.native || !view.editable) return;
      chordTarget = {song: view.song, revision: view.revision, pattern: view.pattern, beat: b.id,
        maxFret: spec().max_fret ?? 29, strings: spec().tuning.length, track};
      invalidateChordRecognition();
      invalidateChordGeneration(); generatorTheoryControls();
      root.querySelector('[data-gen="max_fret"]').placeholder = `Default ${Math.min(15, chordTarget.maxFret)}`;
      const chord = b.chord || {name: '', first_fret: 0, frets: spec().tuning.map(() => -1)};
      ui('chord-velocity').value = chordEntryVelocity; ui('chord-remove-ties').checked = false;
      ui('chord-name').value = chord.name; ui('chord-first').value = chord.first_fret; ui('chord-first').max = chordTarget.maxFret;
      ui('chord-strings').replaceChildren();
      for (let i = chord.frets.length - 1; i >= 0; i--) {
        const label = text('label', `String ${i + 1}`), input = document.createElement('input');
        label.style.flexDirection = 'column'; input.dataset.chordString = i + 1; input.size = 3; input.style.width = '48px';
        input.setAttribute('aria-label', `String ${i + 1} diagram fret, X muted, 0 open`); input.value = chord.frets[i] < 0 ? 'X' : chord.frets[i];
        label.append(input); ui('chord-strings').append(label);
      }
      root.querySelector('.vt-tab-chord').hidden = false; drawChordDiagram(); ui('chord-name').focus();
      ui('library-name').value = chord.name; libraryControls();
      if (ui('chord-library').open) refreshChordLibrary();
    }
    async function applyChordDiagram(remove = false) {
      if (!chordTarget || busy) return;
      if (chordTarget.song !== view.song || chordTarget.revision !== view.revision)
        return ui('chord-status').textContent = 'The song changed while this diagram was open. Reopen it before saving.';
      try {
        const beat = clone(view.score.patterns[chordTarget.pattern].beats.find(b => b.id === chordTarget.beat));
        beat.chord = remove ? null : readChordDiagram();
        if (await commit({op: 'beat_set', pattern: chordTarget.pattern, beat})) closeChordDiagram();
      } catch (e) { ui('chord-status').textContent = e.message; }
    }
    async function replaceChordNotes() {
      if (!chordTarget || busy) return;
      if (chordTarget.song !== view.song || chordTarget.revision !== view.revision)
        return ui('chord-status').textContent = 'The song changed while this diagram was open. Reopen it before saving.';
      try {
        const chord = readChordDiagram(), value = ui('chord-velocity').value.trim(), velocity = Number(value);
        if (!value || !Number.isInteger(velocity) || velocity < 0 || velocity > 127)
          throw new Error('Entry velocity must be an integer from 0 to 127; 0 means silent attacks.');
        chordEntryVelocity = velocity;
        if (await commit({op: 'chord_notes', pattern: chordTarget.pattern, beat: chordTarget.beat, chord, velocity,
          remove_ties: ui('chord-remove-ties').checked})) closeChordDiagram();
        else ui('chord-status').textContent = root.querySelector('.vt-tab-status').textContent;
      } catch (e) { ui('chord-status').textContent = e.message; }
    }
    function closeChordDiagram() {
      closePanel('chord');
    }
    const gen = name => root.querySelector(`[data-gen="${name}"]`);
    function generatorTheoryControls() {
      const restricted = ['dim', 'dim7', 'aug', '5'].includes(gen('quality').value);
      gen('extension').disabled = restricted; if (restricted) gen('extension').value = '0';
      gen('add').disabled = restricted || gen('extension').value === '0'; if (gen('add').disabled) gen('add').checked = false;
      const disabled = {extension_shift: restricted || gen('extension').value === '0',
        fifth_shift: ['dim','dim7','aug'].includes(gen('quality').value),
        ninth_shift: restricted || +gen('extension').value < 11 || gen('add').checked,
        eleventh_shift: restricted || +gen('extension').value < 13 || gen('add').checked};
      for (const [key, off] of Object.entries(disabled)) { gen(key).disabled = off; if (off) gen(key).value = '0'; }
    }
    function generatorSettings() {
      const integer = (key, min, max, blank = false) => {
        const value = gen(key).value.trim();
        if (blank && !value) return null;
        const n = Number(value);
        if (!value || !Number.isInteger(n) || n < min || n > max) throw new Error(`${gen(key).getAttribute('aria-label')} must be an integer from ${min} to ${max}.`);
        return n;
      };
      const spec = {root: +gen('root').value, quality: gen('quality').value, bass: +(gen('bass').value || gen('root').value),
        extension: +gen('extension').value, add: gen('add').checked, sharp: gen('sharp').value === 'true'};
      for (const key of ['extension_shift','fifth_shift','ninth_shift','eleventh_shift']) spec[key] = +gen(key).value;
      return {spec, profile: gen('profile').value, min_fret: integer('min_fret',0,15),
        max_fret: integer('max_fret',0,25,true), open_strings: gen('open_strings').checked, count: integer('count',1,100)};
    }
    function invalidateChordGeneration() {
      generationToken++; chordGeneration = null; ui('generated-chords').replaceChildren();
      root.querySelector('[data-action="chord-generate"]').disabled = false;
      ui('generation-status').textContent = 'Generate shapes, then select one to copy into the draft.';
    }
    function generationCurrent(request) {
      if (!chordTarget || chordTarget !== request.target || view.song !== request.song || view.revision !== request.revision) return false;
      try { return JSON.stringify(generatorSettings()) === request.settings; } catch (_) { return false; }
    }
    async function generateChordShapes() {
      if (!chordTarget) return;
      if (chordTarget.song !== view.song || chordTarget.revision !== view.revision)
        return ui('generation-status').textContent = 'The song changed. Reopen the diagram before generating shapes.';
      let token;
      try {
        const settings = generatorSettings(); invalidateChordGeneration(); token = generationToken;
        const request = {target: chordTarget, song: view.song, revision: view.revision, settings: JSON.stringify(settings)};
        root.querySelector('[data-action="chord-generate"]').disabled = true;
        ui('generation-status').textContent = 'Generating shapes…';
        const response = await fetch('/api/chord_generate', {method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify({revision: request.revision, track: request.target.track, ...settings})});
        const result = await response.json();
        if (destroyed || token !== generationToken) return;
        if (!generationCurrent(request)) return invalidateChordGeneration();
        if (!response.ok || result.error) throw new Error(result.error || `Generation failed (${response.status}).`);
        if (result.revision !== request.revision || result.track !== request.target.track) throw new Error('Generation context changed. Generate again.');
        chordGeneration = {request, chords: result.chords};
        ui('generated-chords').replaceChildren(...result.chords.map((chord, index) => {
          const button = text('button', `${index + 1}. ${chord.name}`); button.type = 'button';
          button.dataset.generatedIndex = index; button.setAttribute('aria-pressed', 'false');
          button.setAttribute('aria-label', `Shape ${index + 1}: ${chord.name}, strings 1 to ${chord.frets.length}: ${chord.frets.map(f=>f<0?'X':f).join(', ')}`);
          button.style.cssText = 'display:flex;flex-direction:column;align-items:center';
          const svg = document.createElementNS('http://www.w3.org/2000/svg','svg'); svg.setAttribute('aria-hidden','true');
          drawChordShape(svg, chord); svg.style.cssText = 'width:150px;height:135px;max-width:100%'; button.append(svg); return button;
        }));
        ui('generation-status').textContent = result.chords.length ?
          `${result.chords.length} shape(s), in source order · ${result.settings.profile} · frets ${result.settings.min_fret}–${result.settings.max_fret}. Select a shape to load only the draft.` :
          'No shapes found for these settings. Try another range or chord; the draft is unchanged.';
      } catch (e) { if (!destroyed && (token == null || token === generationToken)) ui('generation-status').textContent = e.message; }
      finally { if (!destroyed && token === generationToken) root.querySelector('[data-action="chord-generate"]').disabled = false; }
    }
    listen(ui('generated-chords'), 'click', e => {
      const button = e.target.closest('[data-generated-index]'); if (!button) return;
      if (!chordGeneration || !generationCurrent(chordGeneration.request)) {
        invalidateChordGeneration(); ui('generation-status').textContent = 'The song or generator settings changed. Generate shapes again.'; return;
      }
      const chord = clone(chordGeneration.chords[+button.dataset.generatedIndex]);
      ui('chord-name').value = chord.name; ui('chord-first').value = chord.first_fret;
      for (const input of ui('chord-strings').querySelectorAll('input')) {
        const fret = chord.frets[+input.dataset.chordString-1]; input.value = fret < 0 ? 'X' : fret;
      }
      for (const b of ui('generated-chords').querySelectorAll('button')) b.setAttribute('aria-pressed', String(b === button));
      invalidateChordRecognition(); drawChordDiagram();
      ui('generation-status').textContent = 'Shape copied into the draft. Apply annotation, replace voice notes, or save to the library explicitly.';
    });
    function invalidateChordRecognition() {
      recognitionToken++; chordRecognition = null;
      const option = text('option', 'Recognize names first'); option.value = '';
      ui('recognized-name').replaceChildren(option);
      root.querySelector('[data-action="chord-recognize"]').disabled = false;
      root.querySelector('[data-action="recognition-apply"]').disabled = true;
      ui('recognition-status').textContent = 'Recognition suggests names from the current fret shape and track tuning without capo. Apply a proposed name explicitly.';
    }
    function recognitionCurrent(request) {
      if (!chordTarget || chordTarget !== request.target || view.song !== request.song || view.revision !== request.revision ||
          ui('recognition-spelling').value !== request.spelling) return false;
      try { return JSON.stringify(readChordDiagram()) === request.diagram; } catch (_) { return false; }
    }
    async function recognizeChordNames() {
      if (!chordTarget) return;
      if (chordTarget.song !== view.song || chordTarget.revision !== view.revision)
        return ui('recognition-status').textContent = 'The song changed. Reopen the diagram before recognizing names.';
      let token;
      try {
        const chord = readChordDiagram();
        invalidateChordRecognition(); token = recognitionToken;
        const request = {target: chordTarget, song: view.song, revision: view.revision,
          spelling: ui('recognition-spelling').value, diagram: JSON.stringify(chord)};
        root.querySelector('[data-action="chord-recognize"]').disabled = true;
        ui('recognition-status').textContent = 'Recognizing names…';
        const response = await fetch('/api/chord_recognize', {method: 'POST', headers: {'content-type': 'application/json'},
          body: JSON.stringify({revision: request.revision, track: request.target.track, chord, sharp: request.spelling === 'sharp'})});
        const result = await response.json();
        if (destroyed || token !== recognitionToken) return;
        if (!recognitionCurrent(request)) return invalidateChordRecognition();
        if (!response.ok || result.error) throw new Error(result.error || `Recognition failed (${response.status}).`);
        if (result.revision !== request.revision || result.track !== request.target.track)
          throw new Error('Recognition context changed. Recognize the current draft again.');
        chordRecognition = {request, proposals: result.proposals};
        const placeholder = text('option', result.proposals.length ? 'Choose a proposed name' : 'No names found'); placeholder.value = '';
        ui('recognized-name').replaceChildren(placeholder, ...result.proposals.map((p, i) => {
          const option = text('option', p.name); option.value = i; return option;
        }));
        ui('recognition-status').textContent = result.proposals.length ?
          `${result.proposals.length} proposed name(s), in source order. Fret-shape naming uses track tuning without capo. Choose a name to change only the draft label.` :
          'No names found for this fret shape. The authored name and frets are unchanged.';
      } catch (e) { if (!destroyed && (token == null || token === recognitionToken)) ui('recognition-status').textContent = e.message; }
      finally { if (!destroyed && token === recognitionToken) root.querySelector('[data-action="chord-recognize"]').disabled = false; }
    }
    function applyRecognizedName() {
      if (!chordRecognition || !recognitionCurrent(chordRecognition.request)) {
        invalidateChordRecognition(); ui('recognition-status').textContent = 'The diagram or song changed. Recognize names again.'; return;
      }
      const selected = ui('recognized-name').value, proposal = selected === '' ? null : chordRecognition.proposals[Number(selected)];
      if (!proposal) return;
      ui('chord-name').value = proposal.name; invalidateChordRecognition(); drawChordDiagram();
      ui('recognition-status').textContent = 'Name applied to the draft only. Frets, song and library are unchanged.';
    }
    listen(ui('recognized-name'), 'change', () => {
      root.querySelector('[data-action="recognition-apply"]').disabled = !chordRecognition || ui('recognized-name').value === '';
    });
    listen(root.querySelector('.vt-tab-chord'), 'input', e => {
      drawChordDiagram();
      if (e.target.dataset.gen) { generatorTheoryControls(); invalidateChordGeneration(); }
      if (e.target.dataset.chordString || ['chord-name', 'chord-first', 'recognition-spelling'].includes(e.target.dataset.ui))
        invalidateChordRecognition();
    });
    listen(root.querySelector('.vt-tab-chord'), 'submit', e => { e.preventDefault(); applyChordDiagram(); });
    function libraryControls() {
      const selected = !!chordLibrary?.chords.some(c => c.name === ui('library-chord').value);
      ui('library-chord').disabled = libraryBusy || !chordLibrary;
      ui('library-name').disabled = libraryBusy;
      for (const action of ['load', 'rename', 'remove'])
        root.querySelector(`[data-action="library-${action}"]`).disabled = libraryBusy || !selected || !chordTarget;
      root.querySelector('[data-action="library-add"]').disabled = libraryBusy || !chordLibrary || !chordTarget;
      root.querySelector('[data-action="library-refresh"]').disabled = libraryBusy;
    }
    function showChordLibrary(document, selected = ui('library-chord').value) {
      chordLibrary = document;
      const placeholder = text('option', document.chords.length ? 'Choose a saved shape' : 'No saved shapes'); placeholder.value = '';
      ui('library-chord').replaceChildren(placeholder, ...document.chords.map(c => {
        const option = text('option', `${c.name} · ${c.frets.length} strings`); option.value = c.name; return option;
      }));
      ui('library-chord').value = document.chords.some(c => c.name === selected) ? selected : '';
    }
    async function libraryRequest(edit = null) {
      const response = await fetch('/api/chord_library', edit ? {method: 'POST',
        headers: {'content-type': 'application/json'}, body: JSON.stringify(edit)} : {});
      const document = await response.json();
      if (!response.ok || document.error) throw new Error(document.error || `Library request failed (${response.status}).`);
      return document;
    }
    async function refreshChordLibrary() {
      if (libraryBusy) return;
      libraryBusy = true; libraryControls(); ui('library-status').textContent = 'Loading library…';
      try {
        const document = await libraryRequest(); if (destroyed) return;
        showChordLibrary(document);
        ui('library-status').textContent = `${chordLibrary.chords.length} saved shape(s). Loading does not edit the song.`;
      } catch (e) { chordLibrary = null; if (!destroyed) ui('library-status').textContent = e.message; }
      finally { libraryBusy = false; if (!destroyed) libraryControls(); }
    }
    async function editChordLibrary(op) {
      if (libraryBusy || !chordLibrary || !chordTarget) return;
      try {
        const name = ui('library-name').value;
        if (op !== 'remove' && (!name.trim() || [...name].length > 4096))
          throw new Error('Use a nonblank library name of at most 4096 characters.');
        const selected = ui('library-chord').value;
        const edit = {op, revision: chordLibrary.revision, ...(op === 'add' ? {chord: {...readChordDiagram(), name}} :
          op === 'rename' ? {name: selected, new_name: name} : {name: selected})};
        libraryBusy = true; libraryControls(); ui('library-status').textContent = 'Saving library…';
        const document = await libraryRequest(edit); if (destroyed) return;
        showChordLibrary(document, op === 'remove' ? '' : name);
        ui('library-status').textContent = 'Library saved immediately. Song and draft unchanged; Cancel will not undo this library change.';
      } catch (e) { if (!destroyed) ui('library-status').textContent = e.message; }
      finally { libraryBusy = false; if (!destroyed) libraryControls(); }
    }
    function loadLibraryChord() {
      if (libraryBusy || !chordTarget) return;
      try {
        const stored = chordLibrary?.chords.find(c => c.name === ui('library-chord').value);
        if (!stored) throw new Error('Choose a saved shape first.');
        const chord = clone(stored);
        if (chord.frets.length !== chordTarget.strings)
          throw new Error(`This shape has ${chord.frets.length} strings; the selected track has ${chordTarget.strings}. No strings were added or removed.`);
        if (chord.first_fret > chordTarget.maxFret || chord.frets.some(f => f > chordTarget.maxFret))
          throw new Error(`This shape exceeds the selected track's maximum fret ${chordTarget.maxFret}. The draft was not changed.`);
        ui('chord-name').value = chord.name; ui('chord-first').value = chord.first_fret;
        for (const input of ui('chord-strings').querySelectorAll('input')) {
          const fret = chord.frets[+input.dataset.chordString - 1]; input.value = fret < 0 ? 'X' : fret;
        }
        drawChordDiagram();
        invalidateChordRecognition();
        ui('library-status').textContent = 'Loaded a copy into the draft. Tuning and capo are not stored with this shape; review the frets before applying.';
      } catch (e) { ui('library-status').textContent = e.message; }
    }
    listen(ui('chord-library'), 'toggle', () => { if (ui('chord-library').open) refreshChordLibrary(); });
    listen(ui('library-chord'), 'change', () => {
      const chord = chordLibrary?.chords.find(c => c.name === ui('library-chord').value);
      if (chord) ui('library-name').value = chord.name;
      libraryControls();
    });
    const curvePresets = {
      bend: [
        ['Bend', [[0, 0], [6, 4], [12, 4]]],
        ['Bend and release', [[0, 0], [3, 4], [6, 4], [9, 0], [12, 0]]],
        ['Bend, release, bend', [[0, 0], [2, 4], [4, 4], [6, 0], [8, 0], [10, 4], [12, 4]]],
        ['Prebend', [[0, 4], [12, 4]]],
        ['Prebend and release', [[0, 4], [4, 4], [8, 0], [12, 0]]]
      ],
      tremolo_bar: [
        ['Dip', [[0, 0], [6, -2], [12, 0]]],
        ['Dive', [[0, 0], [9, -2], [12, -2]]],
        ['Release up', [[0, -2], [9, -2], [12, 0]]],
        ['Inverted dip', [[0, 0], [6, 2], [12, 0]]],
        ['Return', [[0, 0], [9, 2], [12, 2]]],
        ['Release down', [[0, 2], [9, 2], [12, 0]]]
      ]
    };
    function curvePoints() {
      const input = ui('curve-points').value.trim();
      const points = input ? input.split(/[,\n]+/).map(part => {
        const match = /^\s*(\d+)\s*:\s*(-?\d+)\s*$/.exec(part);
        if (!match) throw new Error('Use position:value pairs separated by commas or new lines.');
        return {position: Number(match[1]), value: Number(match[2])};
      }) : [];
      const low = curveTarget.flag === 'bend' ? 0 : -12;
      if (points.length > 129 || points.some((p, i) => p.position > 12 || p.value < low || p.value > 12 ||
        i && p.position < points[i - 1].position)) throw new Error(`Use at most 129 points in time order: positions 0–12, values ${low}–12. Equal positions are allowed.`);
      return points;
    }
    function drawCurve() {
      try {
        const points = curvePoints(), low = curveTarget.flag === 'bend' ? 0 : -12;
        const x = p => 25 + p * 310 / 12, y = v => 115 - (v - low) * 100 / (12 - low);
        ui('curve-preview').innerHTML = `<path d="M25 15V115H335 M25 ${y(0)}H335" fill="none" stroke="currentColor" opacity=".4"/>
          <polyline points="${points.map(p => `${x(p.position)},${y(p.value)}`).join(' ')}" fill="none" stroke="currentColor" stroke-width="2"/>
          ${points.map(p => `<circle cx="${x(p.position)}" cy="${y(p.value)}" r="3" fill="currentColor"/>`).join('')}
          <text x="25" y="135" fill="currentColor">0</text><text x="320" y="135" fill="currentColor">12</text>`;
        ui('curve-status').textContent = `${points.length} point${points.length === 1 ? '' : 's'}. Changes apply only when saved.`;
      } catch (e) { ui('curve-preview').replaceChildren(); ui('curve-status').textContent = e.message; }
    }
    function openCurve(flag) {
      const b = current(), notes = noteRange() ? rangeNotes() : b?.notes.filter(n => chosen === 'chord' || selectedNotes.get(b.id)?.has(n.id)) || [];
      if (busy || rawSelected || !view?.native || !view?.editable || !notes.length) return;
      curveTarget = {flag, song: view.song, revision: view.revision, pattern: view.pattern,
        notes: notes.map(n => ({beat: b?.id, id: n.id})),
        selection: noteRange() ? clone(selectedGroups()) : null, track, voice};
      ui('curve-title').textContent = (flag === 'bend' ? 'Bend' : 'Tremolo bar') + ` · ${notes.length} selected note${notes.length === 1 ? '' : 's'}`;
      ui('curve-help').textContent = `Positions run from 0 (start) to 12 (end). Values are ${flag === 'bend' ? 'quarter tones, 0–12 (4 = two semitones)' : 'semitones, −12–12'}. Duplicate positions preserve abrupt changes.`;
      ui('curve-preset').replaceChildren(...[['Custom', null], ...curvePresets[flag]].map(([name], i) => {
        const option = text('option', name); option.value = i - 1; return option;
      }));
      const existing = notes[0][flag];
      const same = notes.every(n => JSON.stringify(n[flag]) === JSON.stringify(existing));
      const points = same && existing != null ? existing.points : curvePresets[flag][0][1].map(([position, value]) => ({position, value}));
      ui('curve-preset').value = existing != null && same ? '-1' : '0';
      ui('curve-points').value = points.map(p => `${p.position}:${p.value}`).join(', ');
      root.querySelector('.vt-tab-curve').hidden = false; drawCurve(); ui('curve-points').focus();
      if (!same) ui('curve-status').textContent = 'Selected notes have different curves. Applying replaces each selected note’s curve.';
    }
    async function applyCurve(remove = false) {
      if (!curveTarget || busy) return;
      if (curveTarget.song !== view.song || curveTarget.revision !== view.revision) return status('The song changed while this curve was open. Reopen the curve before saving.');
      try {
        const value = remove ? null : {points: curvePoints()};
        const saved = curveTarget.selection ? await commandBeats('set_expression', {
          selection: curveTarget.selection, track: curveTarget.track, voice: curveTarget.voice,
          changes: {[curveTarget.flag]: value}}) : await commit({op: 'notes_set', pattern: curveTarget.pattern,
          notes: curveTarget.notes.map(n => ({beat: n.beat, note: {id: n.id, [curveTarget.flag]: value}}))});
        if (saved) closePanel('curve');
      } catch (e) { ui('curve-status').textContent = e.message; }
    }
    listen(ui('curve-preset'), 'change', () => {
      const preset = curvePresets[curveTarget.flag][+ui('curve-preset').value];
      if (preset) { ui('curve-points').value = preset[1].map(p => p.join(':')).join(', '); drawCurve(); }
    });
    listen(ui('curve-points'), 'input', () => { ui('curve-preset').value = '-1'; drawCurve(); });
    listen(root.querySelector('.vt-tab-curve'), 'submit', e => { e.preventDefault(); applyCurve(); });
    function toggleTie() {
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      const b = current(), n = b?.notes.find(n => n.string === string);
      if (!n || chosen === 'chord') return status('Select the destination note on one string first.');
      const to = {occurrence: occurrence(), note: n.id};
      const existing = (view.score.ties || []).find(t => t.to.occurrence === to.occurrence && t.to.note === to.note);
      if (existing) return commit({op: 'tie_delete', from: existing.from, to});
      let pattern = view.pattern, fromOccurrence = occurrence(), boundary = b.at;
      if (cmp(b.at, [0, 1]) === 0 && view.order > 0) {
        pattern = view.orders[view.order - 1]; fromOccurrence = view.score.order_ids[view.order - 1];
        const step = view.score.patterns[pattern]?.row_step || rowStep(), rows = view.rows[view.pattern_names.indexOf(pattern)];
        boundary = rat(step[0] * rows, step[1]);
      }
      const previous = (view.score.patterns[pattern]?.beats || []).filter(p => p.track === track && p.voice === voice && cmp(add(p.at, duration(p.written)), boundary) === 0);
      const candidates = previous.flatMap(p => p.notes).filter(note => {
        const resolved = (view.positions || []).find(p => p.kind === 'note' && atOccurrence(p, view, pattern, fromOccurrence) && p.note === note.id);
        return note.pitch === n.pitch && (resolved?.string ?? note.string) === string;
      });
      if (candidates.length !== 1) return status('A tie needs one preceding contiguous note of the same pitch on this string.');
      lastDigit = null;
      return commit({op: 'tie_set', from: {occurrence: fromOccurrence, note: candidates[0].id}, to});
    }
    function setSpelling(toggle = false) {
      if (isPercussion(spec())) return percussionRefusal();
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      const b = current(), n = b?.notes.find(n => n.string === string);
      if (!n || chosen === 'chord') return status('Select one note on a string first.');
      let spelling = ui('spelling-alter').value === 'auto' ? null : {step: ui('spelling-step').value, alter: +ui('spelling-alter').value};
      if (toggle) {
        if (spec().clef === 'percussion') return status('Enharmonic toggle is unavailable for percussion notation.');
        const normal = keySpelling(n.pitch, spec().key?.fifths), sharp = keySpelling(n.pitch, 7), flat = keySpelling(n.pitch, -7);
        const same = (a, b) => a.step === b.step && (a.alter || 0) === (b.alter || 0);
        const alternate = same(sharp, normal) ? flat : sharp;
        if (same(alternate, normal)) return status('This pitch has no alternate single-accidental spelling.');
        spelling = same(n.spelling || normal, normal) ? alternate : normal;
      }
      return commit({op: 'note_set', pattern: view.pattern, beat: b.id, note: {id: n.id, spelling}});
    }
    async function adoptRaw() {
      if (!rawSelected || !spec()) return status('Select an existing Pattern note and configure its track first.');
      const p = rawSelected, order = view.order, pattern = view.pattern;
      if (view.native && !p.adoptable) return status(p.reason || 'This Pattern note cannot be adopted without changing playback.');
      const saved = await commit({op: 'promote_pattern', pattern: p.pattern, track: p.track || track,
        occurrence: occurrence(), cells: [{row: p.row, ch: p.ch}]});
      if (saved) { rawSelected = null; setSelection({order, pattern, row: p.row, ch: p.ch}); }
    }
    function setDuration(rest = false, action = rest ? 'rest' : 'duration') {
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      if (!spec()) return status('Set up a track first.');
      const b = current();
      if (view.native && rest && noteRange()) return commandBeats('rest');
      const beat = {...(b ? authoredBeat(b) : {id: uid('beat'), track, voice, at: [...at], notes: []}), written: readWritten(), ...(rest ? {notes: []} : {})};
      const ui_context = {action, occurrence: occurrence(), beat: b?.id, voice,
        written: clone(b?.written || written), fit: ui('fit').checked, free: ui('free-edit').checked};
      if (view.native && !rest && crossRange())
        return commandBeats('set_duration', {written: beat.written, ui_context, free: ui('free-edit').checked, ...(ui('fit').checked ? {fit: 'tg_duration'} : {})});
      if (view.native && !rest) {
        const refusal = entryRefusal(); if (refusal) return status(refusal);
        if (!view.editable) return status('Enable editing before changing the score.');
        if (!b || cmp(duration(b.written), duration(beat.written)) !== 0) delete beat.duration_source;
        const target = entryTarget(beat.written);
        // A beat range takes the duration beat by beat, as TuxGuitar's SetDuration does, in one undo step.
        const range = beats().filter(r => selectedBeats.has(r.id) && r.track === track && r.voice === voice).map(r => r.id);
        if (b)
          return queueEntry(target, () => commit({action: 'set_duration', occurrence: target.occurrence, track, voice,
            beats: range.length ? range : [b.id], written: beat.written, ui_context, free: ui_context.free,
            ...(target.fit ? {fit: 'tg_duration'} : {})}, target.revision));
        return queueEntry(target, () => commit({action: 'place', occurrence: target.occurrence, beat,
          ui_context, ...(b && target.fit ? {fit: 'tg_duration'} : {})}, target.revision));
      }
      delete beat.duration_source;
      return commit({op: 'beat_set', pattern: view.pattern, beat, ui_context});
    }
    // Retune/Transpose results: each list of 'pattern/id' as a count, with the first few named
    // Ins, as TuxGuitar's Insert rest (TGInsertRestBeatAction): the model moves this voice's later beats right
    function moveBeats(direction) {
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      if (!spec()) return status('Set up a track first.');
      const raw = ui('move-amount').value.trim(), parts = /^(\d+)(?:\/(\d+))?$/.exec(raw);
      if (raw && (!parts || +parts[1] <= 0 || +(parts[2] || 1) <= 0)) return status('Move amount needs a positive quarter-note count, such as1 or1/2; leave blank for the caret duration.');
      const amount = raw ? rat(+parts[1], +(parts[2] || 1)) : undefined;
      return commit({action: 'move_beats', occurrence: occurrence(), track, voice, at: [...at], direction, ...(amount ? {amount} : {})}, view.revision);
    }
    function insertRest() {
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      if (!spec()) return status('Set up a track first.');
      return commit({action: 'insert_rest', occurrence: occurrence(), track, voice, at: [...at], written: readWritten(),
        rest_id: uid('beat'), ...(ui('free-edit').checked ? {free: true} : {})}, view.revision);
    }
    function changeReport(action, result) {
      const parts = Object.entries(result).filter(([, v]) => Array.isArray(v) && v.length && typeof v[0] === 'string')
        .map(([k, v]) => `${k.replace(/_/g, ' ')} ${v.length}${v.length ? ` (${v.slice(0, 3).join(', ')}${v.length > 3 ? ', …' : ''})` : ''}`);
      if (result.added_channels?.length) parts.push(`added ${result.added_channels.length} string channel(s)`);
      if (result.retired_channels?.length) parts.push(`released ${result.retired_channels.length} string channel(s); raw Pattern data retained`);
      return `${action === 'retune' ? 'Retuned' : 'Transposed'}${parts.length ? ': ' + parts.join('; ') : ': no notes changed'}.`;
    }
    function beatsCommand(action = 'remove_unused_voice') {
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      if (view.native && noteRange() && action === 'clean_beat') return commandBeats(action);
      // Remove unused voice / Clean beat, as TuxGuitar: the selected beats, else the caret's beat.
      const ids = beats().filter(b => b.track === track && selectedBeats.has(b.id)).map(b => b.id);
      if (!ids.length && current()) ids.push(current().id);
      if (!ids.length) return status('Select a beat first.');
      return commit({action, occurrence: occurrence(), track, beats: ids}, view.revision);
    }
    function stepDuration(longer) {
      if (rawSelected) return status('Adopt this Pattern note before editing its notation.');
      const w = readWritten(), value = longer ? w.value / 2 : w.value * 2;
      if (value < 1 || value > 64) return;
      ui('duration').value = value; ui('dots').value = '0';
      return setDuration(false, longer ? 'longer' : 'shorter');
    }
    function remove(whole) {
      if (rawSelected) return status('Delete this note in Pattern, or adopt it before editing notation.');
      if (view.native && noteRange()) return commandBeats(whole ? 'delete_beats' : 'delete');
      const b = current(); if (!b) return;
      const n = b.notes.find(n => n.string === string);
      if (whole) return commit({op: 'beat_delete', pattern: view.pattern, beat: b.id});
      if (n) return commit({op: 'note_delete', pattern: view.pattern, beat: b.id, note: n.id});
    }
    function setStem(stem = ui('beat-stem').value) {
      const b = current();
      if (rawSelected || !b?.notes.length) return;
      if (view.native) return commit({action: 'set_stem', occurrence: occurrence(), track, beat: b.id, stem});
      const beat = authoredBeat(b);
      if (stem === 'inherit') delete beat.stem; else beat.stem = stem;
      return commit({op: 'beat_set', pattern: view.pattern, beat});
    }
    function caretBeats() {
      // The existing engraving projection includes exact written rests and
      // split continuations. It supplies empty-voice timing without authoring
      // beats or adopting any of the raw Pattern notes beneath the staff.
      const origin = (view.occurrences || []).find(o => o.id === occurrence())?.at || [0, 1], limit = add(origin, end());
      const local = renderedBeats.filter(b => b.track === track && cmp(b.end, origin) > 0 && cmp(b.at, limit) < 0)
        .map(b => ({...b, at: cmp(b.at, origin) < 0 ? [0, 1] : sub(b.at, origin)}));
      let list = local.filter(b => b.voice === voice);
      if (!list.length) list = local.filter(b => b.voice === 0);
      return [...new Map((list.length ? list : beats()).map(b => [b.at.join('/'), b.at])).values()].sort(cmp);
    }
    function move(delta) {
      if (!view || !spec() || busy) return;
      const list = caretBeats(), target = delta > 0 ? list.find(p => cmp(p, at) > 0) : list.filter(p => cmp(p, at) < 0).at(-1);
      if (target) return navigateTo(view.order, target);
      const order = view.order + delta;
      if (order < 0 || order >= view.orders.length) return status(delta > 0 ? 'End of the song.' : 'Start of the song.');
      navigateTo(order, delta > 0 ? 'first' : 'last');
    }
    function navigationMeasures() {
      if (rawPreview()) return view.orders.map((name, order) => ({from: {order, at: [0, 1]},
        to: {order, at: rat(view.rows[view.pattern_names.indexOf(String(name))], view.rows_per_beat || 4)}}));
      const ids = view?.score?.order_ids || [], spans = [];
      for (let order = 0; order < ids.length; order++) {
        const pattern = String(view.orders[order]), step = view.score.patterns[pattern]?.row_step || view.row_step;
        const rows = view.rows[view.pattern_names.indexOf(pattern)];
        if (rows && step) spans.push({from: {order, at: [0, 1]}, to: {order, at: rat(rows * step[0], step[1])}});
      }
      const position = p => {
        const order = ids.indexOf(p.occurrence), span = spans.find(s => s.from.order === order);
        return span && order + 1 < ids.length && cmp(p.at, span.to.at) === 0 ? {order: order + 1, at: [0, 1]} : {order, at: p.at};
      };
      const authored = (view?.score?.measures || []).map(m => ({from: position(m.from), to: position(m.to)}));
      return (authored.length ? authored : spans).sort((a, b) => comparePosition(a.from, b.from));
    }
    const comparePosition = (a, b) => a.order - b.order || cmp(a.at, b.at);
    function markers() {
      return (view?.score?.measures || []).filter(m => m.marker).map(m => ({...m,
        position: {order: view.score.order_ids.indexOf(m.from.occurrence), at: m.from.at}}))
        .sort((a, b) => comparePosition(a.position, b.position));
    }
    function drawMarkers() {
      ui('markers').replaceChildren(...markers().map(m => {
        const button = text('button', `${m.marker.title} · ${m.position.order + 1}:${m.from.at.join('/')}`);
        button.type = 'button'; button.dataset.marker = m.id;
        button.style.borderLeft = `6px solid ${m.marker.color || 'currentColor'}`;
        return button;
      }));
    }
    function navigateMarker(next, edge = false) {
      const position = {order: view.order, at}, list = markers();
      const marker = edge ? (next ? list.at(-1) : list[0]) : next ? list.find(m => comparePosition(m.position, position) > 0) :
        list.filter(m => comparePosition(m.position, position) < 0).at(-1);
      if (marker) navigateTo(marker.position.order, marker.position.at);
      else status(next ? 'No later marker.' : 'No earlier marker.');
    }
    // TGSelectAllAction selects the whole written track and refuses duration-error tracks.
    function selectAll() {
      if ((view?.measure_errors || []).some(e => e.track === track))
        return status('Repair this track’s measure-duration errors before Select All.');
      const all = printTimeline(view).source.filter(b => b.track === track).sort((a, b) => cmp(a.at, b.at));
      if (!all.length) return status('No beats on this track.');
      const point = b => ({occurrence: b.sourceOccurrence, at: b.sourceAt});
      selectRange(point(all[0]), point(all.at(-1)));
    }
    // Every beat of the track (both voices) from a to b, inclusive, as TuxGuitar's Selector range
    function selectRange(a, b) {
      const point = p => Array.isArray(p) ? {occurrence: occurrence(), at: p} : p;
      a = point(a); b = point(b);
      const timeline = printTimeline(view), start = add(timeline.offsets.get(a.occurrence), a.at), stop = add(timeline.offsets.get(b.occurrence), b.at);
      const [lo, hi] = cmp(start, stop) < 0 ? [start, stop] : [stop, start];
      const range = timeline.source.filter(x => x.track === track && cmp(x.at, lo) >= 0 && cmp(x.at, hi) <= 0);
      selectionAnchor = {occurrence: a.occurrence, at: [...a.at]};
      const groups = new Map();
      for (const beat of range) {
        const oid = beat.sourceOccurrence;
        if (!groups.has(oid)) groups.set(oid, []);
        groups.get(oid).push(beat.id);
      }
      rangeSelection = [...groups].map(([occurrence, beats]) => ({occurrence, beats}));
      selectedBeats = new Set(groups.get(occurrence()) || []);
      selectedNotes = new Map(beats().filter(x => selectedBeats.has(x.id)).map(x => [x.id, new Set(x.notes.map(n => n.id))]));
      navigationEcho = {...selection(), song: view.song, revision: view.revision};
      controls(); drawGrid(); markEditCaret();
      status(`Selected ${range.length} beat${range.length === 1 ? '' : 's'}.`);
    }
    // TuxGuitar's Extend selection left/right/previous/next/first/last: the caret moves, the first beat stays.
    // Measures are the TAB's authored bars or display groups across written order occurrences.
    function extendSelection(kind) {
      const anchor = selectionAnchor && (selectedBeats.size || rangeSelection.length) ? selectionAnchor : {occurrence: occurrence(), at: [...at]};
      const timeline = printTimeline(view), absolute = add(timeline.offsets.get(occurrence()), at);
      const starts = [...new Map(timeline.source.filter(b => b.track === track).map(b => [b.at.join('/'), b.at])).values()].sort(cmp);
      let target;
      if (kind === 'left') target = starts.filter(x => cmp(x, absolute) < 0).at(-1);
      else if (kind === 'right') target = starts.find(x => cmp(x, absolute) > 0);
      else if (kind === 'first') target = starts[0];
      else if (kind === 'last') target = starts.at(-1);
      else {
        const measures = timeline.ranges;
        const inside = m => m ? starts.filter(x => cmp(x, m.from) >= 0 && cmp(x, m.to) < 0) : [];
        const i = measures.findIndex(m => cmp(m.from, absolute) <= 0 && cmp(absolute, m.to) < 0), own = inside(measures[i]);
        if (kind === 'next') target = own.length && cmp(absolute, own.at(-1)) !== 0 ? own.at(-1) : inside(measures[i + 1]).at(-1);
        else target = own.length && cmp(absolute, own[0]) !== 0 ? own[0] : inside(measures[i - 1])[0];
      }
      if (!target) return status('The selection cannot extend past the written song.');
      const [oid, origin] = [...timeline.offsets].filter(([, start]) => cmp(start, target) <= 0).at(-1);
      const position = sub(target, origin);
      navigateTo(view.score.order_ids.indexOf(oid), position);
      selectRange(anchor, {occurrence: oid, at: position});
    }
    function runAction(name) {
      if (isPercussion(spec()) && drumActions.has(name)) return percussionRefusal();
      return Promise.resolve(actions[name]()).catch(err => status(err.message || String(err)));
    }
    function navigateTo(order, position) {
      if (!view || busy || order < 0 || order >= view.orders.length) return;
      if (rawPreview()) {
        update({...view, order, pattern: String(view.orders[order])});
        host.select({order, pattern: view.pattern, row: 0, ch: Math.max(0, previewChannel), source: 'raw'});
        const first = renderedBeats.find(b => b.order === order), bounds = first && api?.boundsLookup.findBeats(first.beat)?.[0];
        if (bounds) {
          if (viewPrefs.layout === 'horizontal') scoreHost.scrollLeft = Math.max(0, bounds.onNotesX - 40);
          else {
            const container = root.closest('.main'), surface = scoreHost.querySelector('.at-surface');
            if (container && surface) container.scrollTop += surface.getBoundingClientRect().top + bounds.barBounds.visualBounds.y - container.getBoundingClientRect().top;
          }
        }
        return;
      }
      const changingOrder = order !== view.order, keepEcho = changingOrder || navigationEcho;
      if (changingOrder) update({...view, order, pattern: String(view.orders[order])});
      if (typeof position === 'string') position = (position === 'last' ? caretBeats().at(-1) : caretBeats()[0]) || [0, 1];
      choose(position, string, false, false);
      const selected = selection();
      if (keepEcho) navigationEcho = {...selected, song: view.song, revision: view.revision};
      notifying = true; try { host.select(selected); } finally { notifying = false; }
      engrave(); revealEditCaret(); root.focus({preventScroll: true});
    }
    function navigateMeasure(command) {
      if (!view || busy) return;
      const list = navigationMeasures(), position = {order: view.order, at};
      const currentIndex = list.findIndex(m => comparePosition(m.from, position) <= 0 && comparePosition(position, m.to) < 0);
      let target;
      if (command === 'first') target = list[0];
      else if (command === 'last') target = list.at(-1);
      else if (currentIndex >= 0) target = list[currentIndex + (command === 'next' ? 1 : -1)];
      else target = command === 'next' ? list.find(m => comparePosition(m.from, position) > 0) : list.filter(m => comparePosition(m.from, position) < 0).at(-1);
      if (target) navigateTo(target.from.order, target.from.at);
      else status(command === 'next' || command === 'last' ? 'Last measure.' : 'First measure.');
    }
    function chooseContext(nextAt) {
      const follow = following(), playing = !!(playhead || host.isPlaying?.());
      choose(nextAt);
      // Part/voice context changes synchronize the editing caret without
      // requesting that the shared playback position stop being followed.
      ui('follow').checked = follow;
      if (playing) { revealCaret = false; root.focus({preventScroll: true}); }
      return playing;
    }
    function selectVoice(value) {
      voice = value; ui('voice').value = voice;
      chooseContext(at); markPlayhead();
    }
    function selectTrack(id, accepted = false) {
      if (rawPreview()) { const ch = Number(id); if (!Number.isInteger(ch) || ch < -2 || ch >= view.channels.length) return;
        previewChannel = ch; rawSelected = null; controls(); drawRaw(); engrave(); return; }
      if (!view?.score?.tracks[id] || busy && !accepted) return;
      const position = {order: view.order, at}, measure = navigationMeasures().find(m => comparePosition(m.from, position) <= 0 && comparePosition(position, m.to) < 0);
      track = id; ui('track').value = track; renderKey = '';
      const beat = beats().find(b => cmp(b.at, at) <= 0 && cmp(add(b.at, duration(b.written)), at) > 0);
      let target = beat?.at || at;
      // A cross-pattern measure can begin inside a sustained native beat.
      // Keep the caret in that measure instead of jumping back to its origin.
      if (measure?.from.order === view.order && cmp(target, measure.from.at) < 0) target = measure.from.at;
      const playing = chooseContext(target);
      engrave();
      if (!playing) revealEditCaret();
    }
    function navigateTrack(command) {
      const ids = Object.keys(view?.score?.tracks || {}), index = ids.indexOf(track);
      const next = command === 'first' ? 0 : command === 'last' ? ids.length - 1 : index + (command === 'next' ? 1 : -1);
      if (ids[next]) selectTrack(ids[next]);
      root.focus();
    }
    function copyBeats() {
      const pendingCopy = copying = (async () => {
        await fretChain; await saving;
        if (destroyed || rawSelected) return false;
        const ids = allBeats().filter(b => b.track === track && (selectedBeats.has(b.id) || !selectedBeats.size && b.id === current()?.id)).map(b => b.id);
        if (!ids.length && !rangeSelection.length) { status('Select authored beats to copy. Ctrl+click adds or removes beats.'); return false; }
        try {
          const qualified = crossRange();
          const sourceSong = view.song;
          const copied = await host.copy(qualified ? {selection: clone(rangeSelection)} : {pattern: view.pattern, beats: ids, occurrence: occurrence()});
          clipboard = copied; clipboardSong = sourceSong; measureClip = measureClipSong = null;
          const count = clipboard.beats.length;
          if (!destroyed) { controls(); status(`Copied ${count} beat${count === 1 ? '' : 's'}. Ctrl+click selects multiple beats.`); }
          return true;
        } catch (e) { if (!destroyed) status(`Copy refused: ${e.message || e}`); return false; }
      })();
      pendingCopy.finally(() => { if (copying === pendingCopy) copying = null; });
      return pendingCopy;
    }
    function pasteTarget() {
      const timeline = printTimeline(view), groups = selectedGroups();
      const first = timeline.source.filter(b => b.track === track && groups.some(g =>
        g.occurrence === b.sourceOccurrence && g.beats.includes(b.id))).sort((a,b) => cmp(a.at,b.at))[0];
      const oid = first?.sourceOccurrence || occurrence(), order = view.score.order_ids.indexOf(oid);
      return {song: view.song, revision: view.revision, track, pattern: String(view.orders[order]), order,
        occurrence: oid, at: first ? [...first.sourceAt] : [...at]};
    }
    function openClipboardMeasures() {
      drawMeasures(); loadMeasure(); measureOps(true); panel('measures').hidden = false; ui('ops-from').focus();
    }
    function copyContext() {
      if (view?.native && !rawSelected && !rangeSelection.length && !selectionAnchor && selectedBeats.size <= 1)
        return openClipboardMeasures();
      return copyBeats();
    }
    async function pasteContext() {
      const target = {song: view?.song, order: view?.order, revision: view?.revision}, pendingCopy = copying;
      if (pendingCopy && await pendingCopy === false) return;
      if (destroyed || target.song !== view?.song || target.order !== view?.order || !pendingCopy && target.revision !== view?.revision) return;
      if (measureClip) return openClipboardMeasures();
      return pasteBeats(!!view?.native, view?.native ? 'tg_replace' : null);
    }
    async function pasteBeats(replace = false, mode = null) {
      const target = pasteTarget(), caret = {order:view.order, at:[...at], track};
      const pendingCopy = copying;
      if (pendingCopy && await pendingCopy === false) return;
      await fretChain; await saving;
      if (destroyed || target.song !== view?.song || target.revision !== view?.revision ||
          caret.order !== view?.order || caret.track !== track || cmp(caret.at,at) !== 0) return;
      if (!clipboard) return status('Copy authored beats first.');
      const step = view.score.patterns[target.pattern]?.row_step || view.row_step;
      const row = rat(target.at[0] * step[1], target.at[1] * step[0]);
      if (!view.native && row[1] !== 1) return status('Paste position must align with a Pattern row.');
      const sources = [...new Set(clipboard.beats.map(b => b.track))];
      const track_map = view.native && sources.length === 1 && (sources[0] !== track || clipboardSong !== view.song) ? {[sources[0]]: track} : undefined;
      return commit({op: 'beats_paste', pattern: view.pattern_names.indexOf(target.pattern),
        row: view.native ? row : num(row), clipboard: clone(clipboard), occurrence: target.occurrence, across: !!view.native, replace, track_map, ...(mode ? {mode} : {})});
    }
    function commandBeats(action, options = {}) {
      const rangeEdit = ['transpose', 'shift_pitch', 'shift_strings', 'set_expression', 'set_duration', 'rest', 'delete', 'delete_beats', 'clean_beat', 'transfer_voice'].includes(action);
      const request = crossRange() || rangeEdit || (action === 'cut' && noteRange()) ? {action, track, voice, ...options, selection: clone(options.selection || (rangeSelection.length ? rangeSelection :
        [{occurrence: occurrence(), beats: [...selectedBeats]}]))} :
        {action, occurrence: occurrence(), track, voice, at: [...at], beats: [...selectedBeats],
        notes: [...selectedNotes.values()].flatMap(ids => [...ids])};
      const selectedString = string + (action === 'shift_strings' && current()?.notes.some(n => n.string === string) ? options.direction : 0),
        selectedChord = chosen === 'chord', capturedRevision = view?.revision, previousSave = saving,
        submittedAt = entryTarget(written);
      if (ui('independent').checked) request.independent = true;
      if (!request.beats?.length && !request.selection?.length || busy || rawSelected || !view?.editable || !view?.native || host.isPlaying?.()) return Promise.resolve(false);
      const operation = (async () => {
        await fretChain; await previousSave;
        if (destroyed) return false;
        busy = true; controls(); status('Saving…');
        try {
          const result = await host.command(request, capturedRevision);
          if (result?.error) throw new Error(result.error);
          if (result.clipboard) { clipboard = result.clipboard; clipboardSong = view.song; measureClip = measureClipSong = null; }
          const target = result.selection, order = view.score.order_ids.indexOf(target.occurrence);
          if (order >= 0 && sameEntryPosition(submittedAt)) {
            if (order !== view.order) update({...view, order, pattern: String(view.orders[order])});
            track = target.track; voice = target.voice; ui('voice').value = String(voice);
            choose(target.at, selectedString, action === 'repeat' || selectedChord, false);
            if (action === 'repeat' || rangeEdit || target.range?.length) {
              rangeSelection = clone(target.range || []);
              selectedBeats = new Set(target.beats);
              selectedNotes = new Map(allBeats().filter(b => selectedBeats.has(b.id))
                .map(b => [b.id, new Set(b.notes.map(n => n.id))]));
            }
            navigationEcho = {...selection(), song: view.song, revision: view.revision};
            notifying = true; try { host.select(selection()); } finally { notifying = false; }
          }
          const unchanged = action === 'set_duration' && result.outcomes?.every(o => o === 'unchanged');
          status((unchanged ? 'Duration unchanged.' : rangeEdit ? 'Selected phrase updated; one Undo restores it.' :
            action === 'cut' ? 'Cut saved; one Undo restores the selection.' : 'Repeated at the next beat.') + durationReport(result));
          drawGrid(); engrave(); markEditCaret(); return true;
        } catch (e) { status(`${rangeEdit ? 'Range edit' : action === 'cut' ? 'Cut' : 'Repeat'} refused: ${e.message || e}`); return false; }
        finally { busy = false; if (!destroyed) controls(); }
      })();
      saving = operation;
      if (action === 'cut') {
        copying = operation;
        operation.finally(() => { if (copying === operation) copying = null; });
      }
      return operation;
    }
    function preview() {
      const n = current()?.notes?.find(n => n.string === string);
      if (n) Promise.resolve(host.preview({action: 'note', pitch: n.pitch, velocity: n.velocity, instrument: n.instrument || spec().instrument, selection: selection()})).catch(e => status(String(e)));
    }
    // Every side panel (Track setup, Lyrics, chord diagram, pitch curve, Transpose, Measures) opens, toggles and closes
    // here: one ✕ Close at its top, Escape, and its toolbar button toggling it. A panel's own state goes in panelCleanup.
    const panel = name => root.querySelector(`form.vt-tab-panel[data-panel="${name}"]`);
    const panelCleanup = {
      lyrics: () => { lyricsTarget = null; },
      chord: () => { chordTarget = null; invalidateChordRecognition(); invalidateChordGeneration(); },
      curve: () => { curveTarget = null; },
    };
    function closePanel(name) {
      const form = panel(name);
      if (!form || form.hidden) return;
      form.hidden = true; panelCleanup[name]?.();
    }
    function togglePanel(name, open) { if (panel(name).hidden) open(); else closePanel(name); }
    for (const form of root.querySelectorAll('form.vt-tab-panel')) {
      const close = text('button', '✕ Close', 'vt-tab-close');
      close.type = 'button'; close.dataset.action = `close-${form.dataset.panel}`; close.setAttribute('aria-label', `Close ${form.getAttribute('aria-label') || form.dataset.panel}`);
      form.prepend(close);
    }
    function setup(fresh = false) {
      refreshTunings();
      const s = fresh ? null : spec(); root.querySelector('.vt-tab-setup').hidden = false;
      ui('name').readOnly = !!s; ui('remove-notes').checked = false;
      if (!s) ui('name').value = fresh ? '' : 'guitar';
      if (s) { ui('name').value = track; ui('tuning').value = s.tuning.map(pitchName).join(' '); ui('channels').value = s.channels.map(c => c + 1).join(','); ui('capo').value = s.capo || 0; ui('instrument').value = s.instrument; ui('max-fret').value = s.max_fret ?? 29; }
      ui('auto-channels').checked = true; ui('channels').disabled = true;
      ui('display-name').value = s?.name || ''; ui('color').value = s?.color || '#222222'; ui('clef').value = s?.clef || 'treble';
      ui('midi-program').value = s?.midi?.program ?? ''; ui('midi-bank').value = s?.midi?.bank ?? '';
      ui('track-kind').value = isPercussion(s) ? 'percussion' : 'pitched';
      ui('track-kind').disabled = !!s && Object.values(view.score.patterns).some(p => p.beats.some(b => b.track === track));
      ui('key-fifths').value = s?.key?.fifths || 0; ui('key-mode').value = s?.key?.mode || 'major'; ui('track-stem').value = s?.stem || 'auto'; controls(); setupShown = setupMeta();
      const importedMix = ['pan','volume'].filter(k => s?.midi?.['source_'+k]).map(k => `${k} ${s.midi['source_'+k].value}`).join(', ');
      ui('midi-source-pan').textContent = importedMix ?
        `Imported MIDI ${importedMix} is preserved on name, program and bank edits. Audio uses the tracker mixer scale. Writing that mixer control replaces its source value; clearing the program or reassigning channels removes the bindings.` : '';
    }
    // Tuning as guitarists read it: note names with octave (scientific: E2 = 40 is the low E string); MIDI numbers
    // are still accepted. TuxGuitar's tuning dialog offers presets the same way; pitches are stored as before.
    function pitchName(p) { return ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'][p % 12] + (Math.floor(p / 12) - 1); }
    function parseTuning(text) {
      return text.split(/[\s,]+/).filter(Boolean).map(t => {
        if (/^\d+$/.test(t)) return Number(t);
        const m = /^([A-Ga-g])([#b\u266f\u266d]?)(-?\d)$/.exec(t);
        return m ? 12 * (+m[3] + 1) + {C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11}[m[1].toUpperCase()] +
          ({'#': 1, '\u266f': 1, b: -1, '\u266d': -1}[m[2]] || 0) : NaN;
      });
    }
    listen(ui('tuning-preset'), 'change', () => {
      const value = ui('tuning-preset').value; if (!value) return;
      const tuning = value.split(',').map(Number), channels = ui('channels').value.split(',').filter(x => x.trim()).length;
      ui('tuning').value = tuning.map(pitchName).join(' '); ui('tuning-preset').value = '';
      if (channels !== tuning.length) status(`This tuning has ${tuning.length} strings: ${ui('auto-channels').checked ? 'channels will be assigned when you apply' : 'give one channel per string before applying'}.`);
    });
    listen(ui('auto-channels'), 'change', () => { ui('channels').disabled = ui('auto-channels').checked; });
    // The owner's rule: a capo change on an existing track takes effect at once, each change one Retune (one Undo),
    // capo only, no Apply. Spinner steps apply as they come, in order; typed digits settle briefly first ("12" is one).
    let capoTimer = 0, capoQueue = Promise.resolve();
    function applyCapo() {
      const value = ui('capo').value, name = ui('name').value;
      if (!ui('name').readOnly || !/^-?\d+$/.test(value) || +value < -24 || +value > 24) return;
      capoQueue = capoQueue.then(async () => {
        while (busy) await saving;
        const s = view?.score?.tracks?.[name];
        if (s && +value !== (s.capo || 0))
          await commit({action: 'retune', track: name, tuning: s.tuning, channels: s.channels, capo: +value,
            max_fret: s.max_fret ?? 29, keep: ui('retune-keep').value}, view.revision);
      });
    }
    listen(ui('capo'), 'input', e => { clearTimeout(capoTimer); if (e.inputType) capoTimer = setTimeout(applyCapo, 600); else applyCapo(); });
    listen(ui('capo'), 'change', () => { clearTimeout(capoTimer); applyCapo(); });
    // The Setup fields other than tuning/strings/capo/maximum fret, as shown: a tuning-only change is one Retune.
    function setupMeta() { return JSON.stringify(['name', 'display-name', 'color', 'clef', 'key-fifths', 'key-mode', 'track-stem',
      'midi-program', 'midi-bank', 'instrument'].map(k => ui(k).value)); }
    var setupShown = null;   // var: the Setup form may be filled before this line runs
    // TuxGuitar's Transpose dialog (defaults: whole track, all tracks, chords, keep strings) as one score command
    let transposeAll = true;
    function transposeScope() {
      const input = ui('transpose-all'), selected = ui('transpose-scope').value === 'selection';
      if (selected && !input.disabled) { transposeAll = input.checked; input.checked = false; }
      if (!selected && input.disabled) input.checked = transposeAll;
      input.disabled = selected;
    }
    listen(ui('transpose-scope'), 'change', transposeScope);
    listen(root.querySelector('.vt-tab-transpose'), 'submit', e => {
      e.preventDefault();
      const semitones = +ui('transpose-semitones').value, scope = ui('transpose-scope').value;
      if (!Number.isInteger(semitones) || semitones < -12 || semitones > 12) return status('Transpose by -12 to 12 semitones.');
      if (!spec()) return status('Set up a track first.');
      if (scope === 'selection') return commandBeats('transpose', {semitones, scope, all_tracks: false,
        apply_to_chords: ui('transpose-chords').checked, try_keep_strings: ui('transpose-strings').checked});
      commit({action: 'transpose', semitones, track, scope, all_tracks: ui('transpose-all').checked,
        apply_to_chords: ui('transpose-chords').checked, try_keep_strings: ui('transpose-strings').checked,
        ...(scope === 'measure' ? {occurrence: occurrence(), at: [...at]} : {})}, view.revision);
    });
    listen(root.querySelector('.vt-tab-setup'), 'submit', e => {
      e.preventDefault(); clearTimeout(capoTimer);
      const parse = input => input.value.split(',').map(x => x.trim()).map(x => x === '' ? NaN : Number(x));
      const automatic = ui('auto-channels').checked;
      const tuning = parseTuning(ui('tuning').value), channels = ui('name').readOnly || !view.score ? parse(ui('channels')).map(c => c - 1) : tuning.map((_, i) => i), capo = +ui('capo').value, instrument = +ui('instrument').value, max_fret = +ui('max-fret').value;
      const name = ui('name').value.trim();
      if (!name || !tuning.length || tuning.length > 25 || (!automatic && tuning.length !== channels.length) || !tuning.every(n => Number.isInteger(n) && n >= 0 && n <= 119) || !channels.every(n => Number.isInteger(n) && n >= 0) || new Set(channels).size !== channels.length || !Number.isInteger(capo) || capo < -24 || capo > 24 || !Number.isInteger(instrument) || instrument < 1 || !Number.isInteger(max_fret) || max_fret < 0 || max_fret > 36) return status('Use valid pitches, fret limits and a distinct existing channel for each string.');
      const program = ui('midi-program').value.trim(), bank = ui('midi-bank').value.trim();
      if (+bank === 128 && (program === '' || tuning.some(n => n !== 0) || capo !== 0))
        return status('Percussion needs an explicit kit program, zero tuning for every lane, and zero capo.');
      if (!ui('midi-program').validity.valid || !ui('midi-bank').validity.valid ||
        program !== '' && (!Number.isInteger(Number(program)) || +program < 0 || +program > 127) ||
        bank !== '' && (!Number.isInteger(Number(bank)) || +bank < 0 || +bank > 16383))
        return status('Use a MIDI program from 0 to 127 and bank from 0 to 16383, or leave them blank.');
      const value = {...(view.score?.tracks?.[name] || {}), tuning, channels, capo, instrument, max_fret,
        name: ui('display-name').value.trim(), color: ui('color').value, clef: ui('clef').value,
        key: {fifths: +ui('key-fifths').value, mode: ui('key-mode').value}, stem: ui('track-stem').value};
      if (program === '') delete value.midi;
      else {
        value.midi = {...value.midi, program: +program};
        if (bank === '') delete value.midi.bank;
        else value.midi.bank = +bank;
      }
      // An existing track's tuning, strings, capo or maximum fret go through Retune (TuxGuitar's tuning change:
      // notes keep their pitch on the best string, or their frets), together with the other setup fields.
      const old = view.score?.tracks?.[name];
      const tuned = {tuning, channels, capo, max_fret}, before = old && {tuning: old.tuning, channels: old.channels,
        capo: old.capo ?? 0, max_fret: old.max_fret ?? 29};
      if (!old) return commit(view.score?.timing === 'native' ? {action:'track_add',track:name,value} : {op:'track_set',track:name,value});
      if (JSON.stringify(before) === JSON.stringify(tuned)) return commit({op: 'track_set', track: name, value});
      const fields = ['name','color','clef','key','stem','midi','instrument'];
      const setup = Object.fromEntries(fields.map(k => [k, value[k] ?? null]));
      commit({action: 'retune', track: name, tuning, capo, max_fret, keep: ui('retune-keep').value,
        ...(automatic ? {auto_channels:true} : {channels}), ...(setupMeta() !== setupShown ? {setup} : {})}, view.revision)
        .then(ok => { if (ok) { ui('channels').value = spec().channels.map(c => c + 1).join(','); setupShown = setupMeta(); } });
    });
    listen(ui('track-kind'), 'change', () => {
      if (ui('track-kind').value === 'percussion') {
        ui('midi-bank').value = 128; ui('midi-program').value ||= '0';
        ui('tuning').value = parseTuning(ui('tuning').value).map(() => 0).join(' '); ui('capo').value = 0;
      } else if (+ui('midi-bank').value === 128) ui('midi-bank').value = 0;
    });
    listen(ui('midi-bank'), 'input', () => { ui('track-kind').value = +ui('midi-bank').value === 128 ? 'percussion' : 'pitched'; });
    // TuxGuitar's Measure menu (Add, Clean, Remove, Copy, Paste) on whole-order measures; the server refuses a song
    // whose measures divide patterns. From/To/Count follow the caret's measure when the panel opens.
    let measureClip = null, measureClipSong = null;
    function measureOps(opening = false) {
      const measures = navigationMeasures(), position = {order:view?.order ?? 0, at};
      const n = (ui('independent').checked ? measures.length : view?.orders?.length) || 1;
      const here = Math.min(n, ui('independent').checked ? Math.max(0, measures.findIndex(m => comparePosition(m.from,position) <= 0 && comparePosition(position,m.to) < 0)) + 1 : (view?.order ?? 0) + 1);
      for (const k of ['ops-from', 'ops-to']) { ui(k).max = n; if (opening) ui(k).value = here; }
      ui('ops-destination').max = n + 1;
      if (opening) ui('ops-destination').value = Math.min(n + 1, here + 1);
      root.querySelector('[data-action="measure-paste"]').disabled = root.querySelector('[data-action="measure-paste-insert"]').disabled = !measureClip;
      const maps = ui('ops-track-map'), signature = JSON.stringify([measureClip?.tracks, Object.keys(view?.score?.tracks || {}), view?.song]);
      if (maps.dataset.signature !== signature) {
        maps.dataset.signature = signature; maps.replaceChildren();
        for (const source of measureClip?.tracks || []) {
          const label = text('label', `${source} → `), select = text('select', '');
          select.dataset.sourceTrack = source;
          select.setAttribute('aria-label', `Paste ${source} into track`);
          for (const [id, spec] of Object.entries(view.score.tracks)) {
            const option = text('option', spec.name || id); option.value = id; select.append(option);
          }
          select.value = measureClip.tracks.length === 1 ? track : (view.score.tracks[source] ? source : Object.keys(view.score.tracks)[measureClip.tracks.indexOf(source)] || track);
          label.append(select); maps.append(label);
        }
      }
    }
    function opsSpan() { const a = +ui('ops-from').value - 1, b = +ui('ops-to').value - 1; return [Math.min(a, b), Math.max(a, b)]; }
    async function measureCommand(edit) {
      const count = +ui('ops-count').value;
      if (await commit({...edit, ...(['measure_add', 'measure_paste'].includes(edit.action) ? {count} : {})}, view.revision)) measureOps();
    }
    async function copyMeasures() {
      const [a, b] = opsSpan(), all = ui('ops-all').checked, sourceSong = view.song, sourceTrack = track;
      const pendingCopy = copying = (async () => {
        try {
          if (a < 0 || b >= (ui('independent').checked ? navigationMeasures().length : view.orders.length))
            throw new Error('Choose measures that exist.');
          const copied = await host.copyMeasures({from: a, to: b, track: all ? null : sourceTrack, copy_markers: ui('ops-markers').checked,
            ...(ui('independent').checked ? {independent:true} : {})});
          measureClip = copied; measureClipSong = sourceSong; clipboard = clipboardSong = null;
          ui('ops-track-map').dataset.signature = '';
          measureOps(); controls(); status(`Copied measure${b > a ? 's' : ''} ${a + 1}${b > a ? `–${b + 1}` : ''} (${all ? 'all tracks' : sourceTrack}).`);
          return true;
        } catch (e) { status(`Copy refused: ${e.message || e}`); return false; }
      })();
      pendingCopy.finally(() => { if (copying === pendingCopy) copying = null; });
      return pendingCopy;
    }
    function pasteMeasures(mode) {
      if (!measureClip) return status('Copy measures first.');
      const track_map = Object.fromEntries([...ui('ops-track-map').querySelectorAll('select')].map(s => [s.dataset.sourceTrack, s.value]));
      return measureCommand({action: 'measure_paste', mode, at: +ui('ops-from').value - 1, segment: measureClip, track,
        track_map, copy_headers: ui('ops-headers').checked, copy_markers: ui('ops-markers').checked});
    }
    function drawMeasures() {
      const selected = ui('measure').value, ids = view?.score?.order_ids || [];
      const entries = (view?.score?.measures || []).filter(m => ids.indexOf(m.from.occurrence) <= view.order && ids.indexOf(m.to.occurrence) >= view.order);
      ui('measure').replaceChildren(...[text('option', 'New measure'), ...entries.map(m => { const o = text('option', `${m.id} · ${m.meter.join('/')} · ${m.from.at.join('/')} → ${m.to.at.join('/')}`); o.value = m.id; return o; })]);
      ui('measure').firstChild.value = ''; ui('measure').value = entries.some(m => m.id === selected) ? selected : '';
      for (const side of ['from', 'to']) {
        const select = ui(`measure-${side}-occ`), previous = select.value;
        select.replaceChildren(...ids.map((id, index) => { const o = text('option', `${index + 1}: ${view.orders[index]} (${id})`); o.value = id; return o; }));
        select.value = ids.includes(previous) ? previous : occurrence();
      }
      root.querySelector('[data-action="delete-measure"]').disabled = !ui('measure').value || busy || !view?.editable;
      drawTempo();
    }
    function tempoTarget() {
      const measure = (view?.score?.measures || []).find(m => m.id === ui('measure').value);
      const point = measure?.from || {occurrence: occurrence(), at: [0, 1]};
      const order = (view?.score?.order_ids || []).indexOf(point.occurrence);
      const pattern = order >= 0 ? String(view.orders[order]) : null;
      const command = (view?.tempo_commands || []).find(c => c.pattern === pattern && cmp(c.at, point.at) === 0);
      return {point, pattern, command, measure};
    }
    function tempoControls() {
      const {command, pattern} = tempoTarget();
      const disabled = busy || !view?.editable || !view?.native || !pattern || command?.automation != null;
      ui('tempo-bpm').disabled = ui('tempo-scope').disabled = disabled;
      root.querySelector('[data-action="tempo-set"]').disabled = disabled;
      root.querySelector('[data-action="tempo-clear"]').disabled = disabled || !command;
    }
    function drawTempo() {
      const {point, pattern, command, measure} = tempoTarget();
      const origin = view?.occurrences?.find(o => o.id === point.occurrence)?.at;
      const absolute = origin ? add(origin, point.at) : null;
      const effective = absolute ? (view.tempos || []).filter(t => cmp(t.at, absolute) <= 0).at(-1)?.bpm ?? view.tempo : view?.tempo;
      ui('tempo-target').textContent = pattern ? `${measure ? 'Saved measure start' : 'Occurrence start'} · ${point.occurrence} · ${point.at.join('/')} quarter notes` : '';
      const unit = measure?.tempo_unit, names = {1: 'whole', 2: 'half', 4: 'quarter', 8: 'eighth', 16: '16th', 32: '32nd', 64: '64th'};
      ui('tempo-effective').textContent = effective != null ? `Effective: ${effective} BPM` +
        (unit ? unitQuarterTempo(unit) === effective ? ` · written ${unit.value} ${unit.dotted ? 'dotted ' : ''}${names[unit.base]}s per minute` : ' · written tempo is stale; score shows the effective quarter-note tempo' : '') : '';
      ui('tempo-bpm').value = command?.bpm ?? '';
      const uses = (view?.orders || []).filter(p => String(p) === pattern).length;
      ui('tempo-help').textContent = !view?.native ? 'Tempo editing requires a native score.' :
        command?.automation != null ? `Controlled by automation ${command.automation}. Edit the automation lane or use MAKE EDITABLE.` :
        `${measure ? 'Uses the saved measure start; apply endpoint edits separately.' : 'With New measure selected, tempo applies at the start of the current occurrence.'}${uses > 1 ? ` This pattern has ${uses} uses. Choose Pattern — all uses, or use SONG → Make unique first.` : ''}`;
      tempoControls();
    }
    async function applyTempo(clear = false) {
      if (busy || !view?.native) return;
      const {point} = tempoTarget(), value = ui('tempo-bpm').value.trim(), bpm = clear ? null : Number(value);
      if (!clear && (!value || !ui('tempo-bpm').validity.valid || !Number.isInteger(bpm) || bpm < 32 || bpm > 255))
        return status('Tempo must be an integer from 32 to 255 BPM. Use Clear change to remove it.');
      const revision = view.revision, song = view.song, scope = ui('tempo-scope').value;
      if (await commit({op: 'tempo_set', occurrence: point.occurrence, at: [...point.at], bpm,
                        scope})) drawTempo();
      else if (view.song === song && view.revision === revision && JSON.stringify(tempoTarget().point) === JSON.stringify(point)) {
        // A refused edit refreshes the view. Keep the draft so its scope can be corrected.
        ui('tempo-bpm').value = value; ui('tempo-scope').value = scope;
      }
    }
    function loadMeasure() {
      const m = (view.score?.measures || []).find(m => m.id === ui('measure').value);
      ui('measure-from-occ').value = m?.from.occurrence || occurrence(); ui('measure-to-occ').value = m?.to.occurrence || occurrence();
      ui('measure-from').value = (m?.from.at || at).join('/'); ui('measure-to').value = (m?.to.at || add(at, [1, 1])).join('/');
      ui('meter-n').value = m?.meter[0] || 1; ui('meter-d').value = m?.meter[1] || 4;
      ui('measure-swing').value = m?.swing || 'none';
      const unitSelect = ui('tempo-unit'), writtenUnit = m?.tempo_unit;
      unitSelect.querySelector('[data-imported]')?.remove();
      const unitValue = writtenUnit ? `${writtenUnit.base}${writtenUnit.dotted ? '.' : ''}` : '4';
      if (![...unitSelect.options].some(o => o.value === unitValue)) {
        const name = {1: 'whole', 2: 'half', 4: 'quarter', 8: 'eighth', 16: '16th', 32: '32nd', 64: '64th'}[writtenUnit.base];
        const option = new Option(`${writtenUnit.dotted ? 'dotted ' : ''}${name} (imported)`, unitValue);
        option.dataset.imported = ''; unitSelect.add(option);
      }
      unitSelect.value = unitValue;
      ui('measure-repeat-open').checked = !!m?.repeat_open;
      ui('measure-repeat-close').value = m?.repeat_close || 0;
      // TGRepeatAlternativeDialog: endings used by earlier measures since the last repeat start are disabled.
      const ids = view.score?.order_ids || [], start = mm => [ids.indexOf(mm.from.occurrence), ...mm.from.at];
      const here = m ? start(m) : [view.order, ...at], before = (x, y) => x[0] - y[0] || x[1] / x[2] - y[1] / y[2];
      let taken = new Set();
      for (const mm of [...(view.score?.measures || [])].sort((x, y) => before(start(x), start(y)))) {
        if (mm === m || before(start(mm), here) >= 0) break;
        if (mm.repeat_open) taken = new Set();
        for (const e of mm.endings || []) taken.add(e);
      }
      for (const box of root.querySelectorAll('[data-ending]')) {
        const e = +box.dataset.ending; box.checked = !!m?.endings?.includes(e); box.disabled = taken.has(e) && !box.checked;
      }
      ui('marker-title').value = m?.marker?.title || ''; ui('marker-color').value = m?.marker?.color || '';
      root.querySelector('[data-action="delete-measure"]').disabled = !m || busy || !view?.editable;
      ui('tempo-scope').value = 'occurrence'; drawTempo();
    }
    listen(ui('measure'), 'change', loadMeasure);
    listen(root.querySelector('.vt-tab-measures'), 'submit', async e => {
      e.preventDefault();
      try {
        const previous = (view.score?.measures || []).find(m => m.id === ui('measure').value);
        const measure = {...clone(previous || {}), id: ui('measure').value || uid('measure'),
          from: {occurrence: ui('measure-from-occ').value, at: readPosition(ui('measure-from').value)},
          to: {occurrence: ui('measure-to-occ').value, at: readPosition(ui('measure-to').value)}, meter: [+ui('meter-n').value, +ui('meter-d').value]};
        if (ui('measure-swing').value === 'none') delete measure.swing;
        else measure.swing = ui('measure-swing').value;
        // TGTempo: `value` beats of the unit per minute play value*4/base quarters (then 3/2 when dotted, both
        // rounded down). The value is the one that plays the measure's current quarter tempo, or the unit refuses.
        const unit = ui('tempo-unit').value, base = parseInt(unit, 10), dotted = unit.endsWith('.');
        const origin = view.occurrences?.find(o => o.id === measure.from.occurrence)?.at;
        const quarter = origin ? (view.tempos || []).filter(t => cmp(t.at, add(origin, measure.from.at)) <= 0).at(-1)?.bpm ?? view.tempo : view.tempo;
        if (unit === '4') delete measure.tempo_unit;
        else if (!(previous?.tempo_unit && `${previous.tempo_unit.base}${previous.tempo_unit.dotted ? '.' : ''}` === unit && unitQuarterTempo(previous.tempo_unit) === quarter)) {
          const plays = value => unitQuarterTempo({value, base, dotted});
          const exact = quarter * base / 4 * (dotted ? 2 / 3 : 1);
          const value = [0, -1, 1, -2, 2].map(d => Math.round(exact) + d).find(v => v > 0 && plays(v) === quarter);
          if (!value) throw new Error(`${quarter} quarter notes per minute has no exact ${ui('tempo-unit').selectedOptions[0].text} value.`);
          measure.tempo_unit = {base, dotted, value};
        }
        if (ui('measure-repeat-open').checked) measure.repeat_open = true;
        else delete measure.repeat_open;
        const close = Number(ui('measure-repeat-close').value), endings = [...root.querySelectorAll('[data-ending]:checked')].map(b => +b.dataset.ending);
        if (!Number.isInteger(close) || close < 0 || close > 100) throw new Error('Repeat additional passes must be an integer from 0 to 100.');
        if (close) measure.repeat_close = close; else delete measure.repeat_close;
        if (endings.length) measure.endings = endings;
        else delete measure.endings;
        if (ui('marker-title').value) {
          measure.marker = {title: ui('marker-title').value};
          if (ui('marker-color').value) measure.marker.color = ui('marker-color').value;
        } else delete measure.marker;
        // TuxGuitar's time signature change: a new bar length (or 'to the end') resizes the measure's pattern and moves
        // later measures; the panel's other fields follow as a second step on the resized entry.
        // Only for a measure that is one whole order with its endpoints left as they were; a measure dividing a pattern
        // keeps the notation-only edit (meter and span together).
        const quarters = mm => mm.meter[0] * 4 / mm.meter[1], same = (x, y) => JSON.stringify(x) === JSON.stringify(y);
        const order = previous ? view.score.order_ids.indexOf(previous.from.occurrence) : -1, name = String(view.orders[order]);
        const step = view.score.patterns[name]?.row_step || view.row_step, rows = view.rows[view.pattern_names.indexOf(name)];
        const whole = previous && previous.from.occurrence === previous.to.occurrence && cmp(previous.from.at, [0, 1]) === 0 &&
          cmp(previous.to.at, rat(rows * step[0], step[1])) === 0 && same(measure.from, previous.from) && same(measure.to, previous.to);
        // An overfull bar (free edit) spans more than its meter: applying the meter shrinks it back when nothing is cut.
        const span = previous && (previous.to.at[0] / previous.to.at[1] - previous.from.at[0] / previous.from.at[1]);
        if (whole && (ui('meter-to-end').checked || quarters(previous) !== quarters(measure) || span !== quarters(measure))) {
          if (!await commit({action: 'measure_meter', at: view.score.order_ids.indexOf(previous.from.occurrence), meter: measure.meter,
            to_end: ui('meter-to-end').checked}, view.revision)) return;
          ui('meter-to-end').checked = false;
          const fresh = (view.score.measures || []).find(m => m.id === measure.id);
          const rest = fresh && {...measure, from: fresh.from, to: fresh.to, meter: fresh.meter};
          if (rest && JSON.stringify(Object.entries(rest).sort()) !== JSON.stringify(Object.entries(fresh).sort())) await commit({op: 'measure_set', measure: rest});
        } else if (!await commit({op: 'measure_set', measure})) return;
        drawMeasures(); ui('measure').value = measure.id; loadMeasure();
      } catch (err) { status(err.message || String(err)); }
    });
    function setBeatStroke(pick) {
      const source = view?.score?.patterns?.[view.pattern]?.beats.find(b => b.id === current()?.id);
      if (!source || rawSelected) return;
      const beat = clone(source), direction = ui(pick ? 'pick-stroke' : 'stroke-direction').value;
      if (pick) beat.pick_stroke = direction || null;
      else {
        const value = Number(ui('stroke-value').value);
        if (direction && ![4, 8, 16, 32, 64].includes(value)) return status('Stroke value must be 4, 8, 16, 32 or 64.');
        beat.stroke = direction ? {direction, value} : null;
      }
      if (noteRange()) return commandBeats('set_expression', {changes: pick ?
        {pick_stroke: beat.pick_stroke} : {stroke: beat.stroke}});
      return commit({op: 'beat_set', pattern: view.pattern, beat});
    }
    listen(ui('track'), 'change', () => selectTrack(ui('track').value));
    listen(ui('follow'), 'change', () => {
      if (!ui('follow').checked) host.select(selection());
      host.refresh?.();
    });
    listen(root, 'input', e => { if (![ui('follow'), ui('track'), ui('voice')].includes(e.target)) pauseFollow(); });
    const scrollHost = root.closest('.main') || root;
    listen(scrollHost, 'wheel', e => {
      // In a horizontal tracker score, vertical scrolling inspects channels,
      // not another point in the song. Keep following time on the other axis.
      if (rawPreview() && viewPrefs.layout === 'horizontal' && !e.shiftKey && Math.abs(e.deltaY) > Math.abs(e.deltaX)) return;
      pauseFollow();
    }, {passive: true});
    listen(scrollHost, 'touchstart', () => pauseFollow(), {passive: true});
    listen(scrollHost, 'pointerdown', e => { if (e.target === root || e.target === scrollHost) pauseFollow(); });
    listen(ui('voice'), 'change', () => selectVoice(+ui('voice').value));
    listen(ui('free-edit'), 'change', () => { freeRequested = ui('free-edit').checked; });
    listen(ui('lane'), 'change', () => { choose(at, +ui('lane').value); revealEditCaret(); });
    listen(ui('fret'), 'input', () => { pending = ''; });
    listen(ui('dynamics'), 'change', () => { if (ui('dynamics').value !== 'custom') ui('velocity').value = ui('dynamics').value; });
    listen(ui('velocity'), 'input', () => { ui('dynamics').value = 'custom'; });
    listen(ui('range-articulation'), 'change', controls);
    listen(ui('harmonic-type'), 'change', () => { ui('harmonic-data').disabled = ['natural', '', 'mixed'].includes(ui('harmonic-type').value); });
    listen(ui('grace-kind'), 'change', graceControls);
    listen(ui('stroke-direction'), 'change', () => { ui('stroke-value').disabled = !ui('stroke-direction').value; });
    listen(ui('repetition-type'), 'change', () => {
      const type = ui('repetition-type').value, value = Number(ui('repetition-value').value);
      repetitionRates(type, (type === 'trill' ? [4, 8, 16, 32, 64] : [8, 16, 32]).includes(value) ? value : 16);
      ui('trill-fret').disabled = type !== 'trill';
      ui('repetition-value').disabled = !['trill', 'tremolo_picking'].includes(type);
    });
    listen(ui('spelling-alter'), 'change', () => { ui('spelling-step').disabled = ui('spelling-alter').value === 'auto'; });
    listen(panel('properties'), 'submit', async event => {
      event.preventDefault();
      const value = Object.fromEntries([...panel('properties').querySelectorAll('[data-credit]')].map(input => [input.dataset.credit, input.value]));
      if (await commit({op:'metadata_set', value})) closePanel('properties');
    });
    function tuningLibrary() { try { const value = JSON.parse(localStorage.getItem('vt-score-tunings') || '{}'); return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; } catch { return {}; } }
    function refreshTunings() {
      const select = ui('custom-tuning'); select.replaceChildren(new Option('choose…', ''));
      for (const name of Object.keys(tuningLibrary()).sort()) select.add(new Option(name, name));
    }
    listen(ui('custom-tuning'), 'change', () => {
      const name = ui('custom-tuning').value, value = tuningLibrary()[name]; if (!value) return;
      ui('tuning-name').value = name; ui('tuning').value = value.tuning.map(pitchName).join(' ');
      ui('capo').value = value.capo; ui('max-fret').value = value.max_fret;
      status('Saved tuning loaded. Apply to retune this track.');
    });
    const actions = {
      'open-grace': () => { inspector.open = true; ui('grace-kind').focus(); },
      'open-text': () => { inspector.open = true; ui('beat-text').focus(); },
      'quick-previous': () => navigateMeasure('previous'), 'quick-next': () => navigateMeasure('next'),
      'prepare-measures': () => measureCommand({action:'prepare_measures'}),
      'jump-bar': () => {
        const index = Number(ui('jump-bar').value), target = navigationMeasures()[index - 1];
        if (!Number.isInteger(index) || !target) return status('Choose an existing bar number.');
        navigateTo(target.from.order, target.from.at);
      },
      'workspace-focus': () => {
        for (const element of [...Object.values(workspacePanels), board]) element.open = false;
        for (const form of root.querySelectorAll('form.vt-tab-panel:not([hidden])')) closePanel(form.dataset.panel);
        root.focus({preventScroll:true}); revealEditCaret();
      },
      'save-template': async () => { try { await host.saveTemplate(ui('template-name').value.trim()); status('Setup template saved; choose it under New song.'); } catch (e) { status(e.message); } },
      'save-tuning': () => {
        const name = ui('tuning-name').value.trim(), tuning = parseTuning(ui('tuning').value), capo = +ui('capo').value, max_fret = +ui('max-fret').value;
        if (!name || !tuning.length || tuning.length > 25 || !tuning.every(n => Number.isInteger(n) && n >= 0 && n <= 119) || !Number.isInteger(capo) || capo < -24 || capo > 24 || !Number.isInteger(max_fret) || max_fret < 0 || max_fret > 36) return status('Use a name and valid tuning, capo and fret limit.');
        const values = tuningLibrary(); values[name] = {tuning,capo,max_fret}; localStorage.setItem('vt-score-tunings', JSON.stringify(values)); refreshTunings(); ui('custom-tuning').value = name; status('Tuning saved.');
      },
      'delete-tuning': () => { const name = ui('custom-tuning').value, values = tuningLibrary(); if (!name) return; delete values[name]; localStorage.setItem('vt-score-tunings', JSON.stringify(values)); refreshTunings(); status('Saved tuning deleted.'); },
      'clone-track': () => commit({action:'track_clone',track}),
      'paste-mix': () => pasteBeats(false, 'mix'), 'paste-push': () => pasteBeats(false, 'push'),
      'move-voice': () => commandBeats('transfer_voice', {from_voice:voice,to_voice:1-voice,mode:ui('voice-transfer-mode').value,copy:false}),
      'copy-voice': () => commandBeats('transfer_voice', {from_voice:voice,to_voice:1-voice,mode:ui('voice-transfer-mode').value,copy:true}),
      'track-up': () => commit({action:'track_move',track,to:Math.max(0,Object.keys(view.score.tracks).indexOf(track)-1)}),
      'track-down': () => commit({action:'track_move',track,to:Math.min(Object.keys(view.score.tracks).length-1,Object.keys(view.score.tracks).indexOf(track)+1)}),
      properties: () => togglePanel('properties', () => {
        const credits = view.score?.metadata || {title:view.title || ''};
        for (const input of panel('properties').querySelectorAll('[data-credit]')) input.value = credits[input.dataset.credit] || '';
        panel('properties').hidden = false;
      }),
      'close-properties': () => closePanel('properties'),
      rehearsal: () => {
        const ranges = view.score.measures || [];
        const chosenOrders = new Set(rangeSelection.map(group => view.score.order_ids.indexOf(group.occurrence)));
        if (!chosenOrders.size) chosenOrders.add(view.order);
        const indices = ranges.map((range, i) => chosenOrders.has(view.score.order_ids.indexOf(range.from.occurrence)) ? i : -1).filter(i => i >= 0);
        host.rehearsal?.({first:indices.length ? Math.min(...indices) : view.order, last:indices.length ? Math.max(...indices) : view.order, track});
      },
      fret: enterFret, duration: () => setDuration(), rest: () => setDuration(true), delete: () => remove(false), 'delete-beat': () => remove(true), 'remove-unused-voice': () => beatsCommand(), 'move-beats-left': () => moveBeats('left'), 'move-beats-right': () => moveBeats('right'), 'clean-beat': () => beatsCommand('clean_beat'), 'insert-rest': () => insertRest(),
      'select-left': () => extendSelection('left'), 'select-right': () => extendSelection('right'),
      'select-previous': () => extendSelection('previous'), 'select-next': () => extendSelection('next'),
      'select-first': () => extendSelection('first'), 'select-last': () => extendSelection('last'),
      'select-all': () => selectAll(), 'select-none': () => { choose(at, string, false, true); status('Selection cleared.'); },
      longer: () => stepDuration(true), shorter: () => stepDuration(false), spelling: () => setSpelling(), enharmonic: () => setSpelling(true),
      undo: () => host.undo(false), redo: () => host.undo(true), play: () => host.transport(selection()), preview,
      chord: () => choose(at, string, true), setup: () => togglePanel('setup', () => { setup(); ui('tuning').focus(); }),
      'new-track': () => setup(true), 'close-setup': () => closePanel('setup'),
      'chord-diagram': () => togglePanel('chord', openChordDiagram),'remove-chord-diagram': () => applyChordDiagram(true),
      'chord-notes': replaceChordNotes,
      'chord-recognize': recognizeChordNames, 'recognition-apply': applyRecognizedName,
      'chord-generate': generateChordShapes,
      lyrics: () => togglePanel('lyrics', openLyrics), 'lyrics-remove': () => saveLyrics(true), 'lyrics-close': () => closePanel('lyrics'), 'close-lyrics': () => closePanel('lyrics'), 'close-chord': () => closePanel('chord'),
      'library-refresh': refreshChordLibrary, 'library-load': loadLibraryChord,
      'library-add': () => editChordLibrary('add'), 'library-rename': () => editChordLibrary('rename'),
      'library-remove': () => editChordLibrary('remove'),
      'close-chord-diagram': closeChordDiagram,
      'delete-track': async () => { const remove_notes = ui('remove-notes').checked; ui('remove-notes').checked = false; if (await commit({action: 'track_remove', track, remove_notes})) closePanel('setup'); },
      measures: () => togglePanel('measures', () => { drawMeasures(); loadMeasure(); measureOps(true); panel('measures').hidden = false; }),
      'measure-add-before': () => measureCommand({action: 'measure_add', at: opsSpan()[0]}),
      'measure-add-after': () => measureCommand({action: 'measure_add', at: opsSpan()[1] + 1}),
      'measure-remove': () => { const [from, to] = opsSpan(); measureCommand({action: 'measure_remove', from, to}); },
      'measure-move': () => { const [from, to] = opsSpan(); measureCommand({action: 'measure_move', from, to, at: +ui('ops-destination').value - 1}); },
      'measure-clean': () => { const [from, to] = opsSpan(); measureCommand({action: 'measure_clean', from, to, track}); },
      'measure-copy': () => copyMeasures(),
      'measure-paste': () => pasteMeasures('replace'),
      'measure-paste-insert': () => pasteMeasures('insert'),
      'measure-unique': () => { const [from, to] = opsSpan(); return measureCommand({action: 'measure_unique', from, to}); },
      'close-measures': () => closePanel('measures'),
      transpose: () => togglePanel('transpose', () => { if (crossRange()) ui('transpose-scope').value = 'selection';
        transposeScope(); panel('transpose').hidden = false; ui('transpose-semitones').focus(); }),
      'close-transpose': () => closePanel('transpose'),
      'delete-measure': async () => { if (ui('measure').value && await commit({op: 'measure_delete', measure: ui('measure').value})) { drawMeasures(); loadMeasure(); } },
      'tempo-set': () => applyTempo(), 'tempo-clear': () => applyTempo(true),
      'beat-stem': () => setStem(),
      stroke: () => setBeatStroke(false), 'pick-stroke': () => setBeatStroke(true),
      'pitch-down': () => changeNote(-1, false), 'pitch-up': () => changeNote(1, false),
      'string-up': () => changeNote(-1, true), 'string-down': () => changeNote(1, true),
      tie: toggleTie, adopt: adoptRaw, copy: copyBeats, paste: pasteContext, 'paste-safe': () => pasteBeats(false), 'paste-replace': () => pasteBeats(true, 'tg_replace'), 'paste-span': () => pasteBeats(true),
      staccato: () => toggleTechnique('staccato'), 'palm-mute': () => toggleTechnique('palm_mute'), dead: () => toggleTechnique('dead'),
      'let-ring': () => toggleTechnique('let_ring'), 'fade-in': () => toggleTechnique('fade_in'), grace: applyGrace,
      'tap-slap-pop': applyTapSlapPop,
      vibrato: () => toggleTechnique('vibrato'), bend: () => togglePanel('curve', () => openCurve('bend')), 'tremolo-bar': () => togglePanel('curve', () => openCurve('tremolo_bar')),
      slide: () => toggleTechnique('slide'),
      ghost: () => toggleTechnique('ghost'), accent: () => toggleTechnique('accent'),
      'heavy-accent': () => toggleTechnique('heavy_accent'), hammer: () => toggleTechnique('hammer'),
      velocity: applyVelocity,
      harmonic: applyHarmonic,
      repetition: applyRepetition,
      'beat-text': () => {
        const source = view?.score?.patterns?.[view.pattern]?.beats.find(b => b.id === current()?.id);
        if (!source || rawSelected) return;
        const beat = clone(source), value = ui('beat-text').value;
        if (value) beat.text = value; else delete beat.text;
        return commit({op: 'beat_set', pattern: view.pattern, beat});
      },
      'remove-curve': () => applyCurve(true), 'close-curve': () => closePanel('curve'),
      cut: () => commandBeats('cut'), repeat: () => commandBeats('repeat'),
      print: () => { if (host.printPreview) return host.printPreview({previewChannel}); status('Print preview is unavailable in this host.'); },
      'track-first': () => navigateTrack('first'), 'track-previous': () => navigateTrack('previous'),
      'track-next': () => navigateTrack('next'), 'track-last': () => navigateTrack('last'),
      'measure-first': () => navigateMeasure('first'), 'measure-previous': () => navigateMeasure('previous'),
      'measure-next': () => navigateMeasure('next'), 'measure-last': () => navigateMeasure('last'),
      'marker-previous': () => navigateMarker(false), 'marker-next': () => navigateMarker(true),
      go: () => { const p = readPosition(ui('at').value); if (cmp(p, end()) >= 0) return status('Position is past the pattern.'); choose(p); }
    };
    // Pinned TuxGuitar defaults are retained where the host has no conflicting
    // transport/file binding. Overrides apply only inside the score editor.
    const shortcutDefaults = {
      'measure-previous':'Ctrl+ArrowLeft', 'measure-next':'Ctrl+ArrowRight',
      'measure-first':'Ctrl+Shift+ArrowLeft', 'measure-last':'Ctrl+Shift+ArrowRight',
      'track-previous':'Ctrl+Shift+ArrowUp', 'track-next':'Ctrl+Shift+ArrowDown',
      'track-first':'', 'track-last':'', 'marker-previous':'Alt+ArrowLeft', 'marker-next':'Alt+ArrowRight',
      'chord-diagram':'a', bend:'b', 'open-grace':'g', 'open-text':'t',
      dead:'x', ghost:'o', hammer:'h', 'palm-mute':'p', slide:'s', vibrato:'v', 'fade-in':'f',
      longer:'+', shorter:'-', properties:'', setup:'', measures:'', rehearsal:'', 'workspace-focus':''
    };
    const shortcutLabels = {'open-grace':'Grace properties','open-text':'Beat text','workspace-focus':'Focus score'};
    const shortcutName = action => shortcutLabels[action] || root.querySelector(`[data-action="${action}"]`)?.textContent.trim() || action;
    let shortcuts = {...shortcutDefaults};
    const fixedKeys = new Set(['e','l','*','/','Enter','Escape','Tab',' ','Delete','Insert',
      'ArrowLeft','ArrowRight','ArrowUp','ArrowDown', 'Shift+ArrowLeft','Shift+ArrowRight','Shift+ArrowUp','Shift+ArrowDown',
      'Alt+Shift+ArrowLeft','Alt+Shift+ArrowRight', 'Ctrl+a','Ctrl+c','Ctrl+x','Ctrl+v','Ctrl+r','Ctrl+y','Ctrl+z','Ctrl+Shift+z',
      'Ctrl+1','Ctrl+2','Ctrl+Delete']);
    function validShortcut(key) {
      return key === '' || typeof key === 'string' && key.length < 40 && !fixedKeys.has(key) && !/^\d$/.test(key) &&
        !/^(?:.*\+)?F\d+$/.test(key) && /^(?:(?:Ctrl\+)?(?:Alt\+)?(?:Shift\+)?)(?:[a-z+\-]|Arrow(?:Left|Right|Up|Down))$/.test(key) &&
        (!key.startsWith('Ctrl+') || Object.values(shortcutDefaults).includes(key));
    }
    try {
      const saved = JSON.parse(localStorage.getItem('vt.scoreShortcuts') || '{}');
      const candidate = {...shortcuts};
      for (const action of Object.keys(candidate)) if (Object.hasOwn(saved, action) && validShortcut(saved[action])) candidate[action] = saved[action];
      const assigned = Object.values(candidate).filter(Boolean);
      if (new Set(assigned).size === assigned.length) shortcuts = candidate;
    } catch (_) {}
    const shortcutEditor = text('div', '', 'vt-tab-shortcut-editor');
    shortcutEditor.innerHTML = `<label>Action <select data-ui="shortcut-action"></select></label>
      <label>Key <input data-ui="shortcut-key" readonly placeholder="Press a key combination" aria-label="Score shortcut"></label>
      <button type="button" data-action="shortcut-save">Assign</button><button type="button" data-action="shortcut-clear">Unbind</button>
      <button type="button" data-action="shortcut-reset">Restore defaults</button>
      <span data-ui="shortcut-status" role="status"></span>
      <p class="vt-tab-help">Score only. F-keys, transport, fret digits, text editing and file shortcuts stay reserved. Use a letter or Alt+letter. Duplicate keys are refused.</p>`;
    help.append(shortcutEditor);
    for (const action of Object.keys(shortcuts)) { const option = text('option', shortcutName(action)); option.value = action; ui('shortcut-action').append(option); }
    function showShortcut() { ui('shortcut-key').value = shortcuts[ui('shortcut-action').value]; }
    function shortcutTitles() {
      for (const [action, key] of Object.entries(shortcuts)) for (const button of root.querySelectorAll(`[data-action="${action}"]`)) {
        button.dataset.shortcutTitle ??= button.title === shortcutDefaults[action] ? '' : button.title;
        button.title = `${button.dataset.shortcutTitle}${button.dataset.shortcutTitle ? ' · ' : ''}Score shortcut: ${key || 'unbound'}`;
      }
    }
    function saveShortcut() {
      const action = ui('shortcut-action').value, key = ui('shortcut-key').value;
      const collision = Object.keys(shortcuts).find(other => other !== action && key && shortcuts[other] === key);
      if (!validShortcut(key) || collision) {
        ui('shortcut-status').textContent = collision ? `Already assigned to ${shortcutName(collision)}.` : 'Reserved shortcut. Use an available letter or Alt+letter.'; return;
      }
      shortcuts[action] = key;
      shortcutTitles();
      try { localStorage.setItem('vt.scoreShortcuts', JSON.stringify(shortcuts)); } catch (_) {}
      ui('shortcut-status').textContent = key ? `${shortcutName(action)}: ${key}` : `${shortcutName(action)} unbound.`;
    }
    actions['shortcut-save'] = saveShortcut;
    actions['shortcut-clear'] = () => { ui('shortcut-key').value = ''; saveShortcut(); };
    actions['shortcut-reset'] = () => { shortcuts = {...shortcutDefaults}; try { localStorage.removeItem('vt.scoreShortcuts'); } catch (_) {} showShortcut(); shortcutTitles(); ui('shortcut-status').textContent = 'Default score shortcuts restored.'; };
    const eventShortcut = e => (e.ctrlKey || e.metaKey ? 'Ctrl+' : '') + (e.altKey ? 'Alt+' : '') +
      (e.shiftKey && (e.key.length !== 1 || /[a-z]/i.test(e.key)) ? 'Shift+' : '') + (e.key.length === 1 ? e.key.toLowerCase() : e.key);
    listen(ui('shortcut-action'), 'change', showShortcut); showShortcut(); shortcutTitles();
    listen(ui('independent'), 'change', () => measureOps(true));
    listen(ui('shortcut-key'), 'keydown', e => {
      if (e.key === 'Tab') return;
      e.preventDefault(); e.stopPropagation();
      if (!['Control','Alt','Shift','Meta'].includes(e.key)) ui('shortcut-key').value = eventShortcut(e);
    });
    listen(root, 'click', e => {
      const markerId = e.target.closest('[data-marker]')?.dataset.marker;
      if (markerId) { const marker = markers().find(m => m.id === markerId); if (marker) navigateTo(marker.position.order, marker.position.at); return; }
      const button = e.target.closest('[data-action]'); if (!button) return;
      if (isPercussion(spec()) && drumActions.has(button.dataset.action)) return percussionRefusal();
      const restoreFocus = document.activeElement === button;
      try {
        Promise.resolve(actions[button.dataset.action]()).catch(err => status(err.message || String(err))).finally(() => {
          if (restoreFocus && !destroyed && document.activeElement === document.body) root.focus({preventScroll: true});
        });
      } catch (err) { status(err.message || String(err)); }
    });
    listen(root, 'keydown', e => {
      if (!root.getClientRects().length) return; // Hidden tabs can retain keyboard focus until the next frame.
      if (e.key === 'Escape') {
        const open = e.target.closest?.('form.vt-tab-panel:not([hidden])') || root.querySelector('form.vt-tab-panel:not([hidden])');
        if (open) {
          e.preventDefault(); e.stopPropagation(); closePanel(open.dataset.panel);
          root.focus({preventScroll: true}); return;
        }
      }
      if (['PageUp', 'PageDown', 'Home', 'End'].includes(e.key) && !/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) pauseFollow();
      if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.target.isContentEditable) {
        if (e.target === ui('fret') && e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); try { enterFret(); } catch (err) { status(err.message); } }
        return;
      }
      // Native buttons must remain operable with Enter/Space rather than being
      // intercepted as fret entry or playback commands by the editor.
      if (e.target.tagName === 'BUTTON' && ['Enter', ' '].includes(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) { e.stopPropagation(); return; }
      if (/^F[5-8]$/.test(e.key)) return;
      const key = eventShortcut(e), shortcut = Object.keys(shortcuts).find(action => shortcuts[action] === key);
      if (shortcut || Object.values(shortcutDefaults).includes(key)) {
        e.stopPropagation(); e.preventDefault();
        if (shortcut) runAction(shortcut);
        return;
      }
      let handled = true;
      try {
        if ((e.ctrlKey || e.metaKey) && !e.altKey && ['ArrowLeft', 'ArrowRight'].includes(e.key)) navigateMeasure(e.key === 'ArrowLeft' ? e.shiftKey ? 'first' : 'previous' : e.shiftKey ? 'last' : 'next');
        else if ((e.ctrlKey || e.metaKey) && !e.altKey && e.shiftKey && ['ArrowUp', 'ArrowDown'].includes(e.key)) navigateTrack(e.key === 'ArrowUp' ? 'previous' : 'next');
        else if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && ['ArrowUp', 'ArrowDown'].includes(e.key)) setStem(e.key === 'ArrowUp' ? 'up' : 'down');
        else if ((e.ctrlKey || e.metaKey) && ['z', 'y'].includes(e.key.toLowerCase())) fretChain.then(() => host.undo(e.key.toLowerCase() === 'y' || e.shiftKey));
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'c') copyContext();
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'x') commandBeats('cut');
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'r') commandBeats('repeat');
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') pasteContext().catch(err => status(err.message || String(err)));
        // TuxGuitar's default keys (dist/tuxguitar-shortcuts.xml, pinned 2c46e2a1) for actions the editor has.
        else if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'a') selectAll();
        else if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && ['1', '2'].includes(e.key)) selectVoice(+e.key - 1);
        else if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key === 'Delete') runAction('clean-beat');
        else if (e.altKey && !e.ctrlKey && !e.metaKey && ['ArrowLeft', 'ArrowRight'].includes(e.key)) navigateMarker(e.key === 'ArrowRight', e.shiftKey);
        else if (e.ctrlKey || e.metaKey || e.altKey) handled = false;
        else if (/^\d$/.test(e.key)) digitFret(+e.key);
        else if (e.key === 'Enter') enterFret();
        else if (e.key === 'Escape') { pending = ''; lastDigit = null; controls(); }
        else if (e.shiftKey && ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) changeNote(['ArrowLeft', 'ArrowUp'].includes(e.key) ? -1 : 1, ['ArrowUp', 'ArrowDown'].includes(e.key));
        else if (e.key === 'ArrowUp') { choose(at, string - 1); revealEditCaret(); }
        else if (e.key === 'ArrowDown') { choose(at, string + 1); revealEditCaret(); }
        else if (e.key === 'ArrowLeft') move(-1);
        else if (e.key === 'ArrowRight') move(1);
        else if (e.key === 'Delete') remove(!noteRange() && chosen === 'chord');
        else if (e.key === 'Insert') insertRest();
        else if (e.key === '+' || e.key === '-') stepDuration(e.key === '+');
        else if (e.key.toLowerCase() === 'e') setSpelling(true);
        else if (e.key.toLowerCase() === 'l') toggleTie();
        else if (e.key === '*') { ui('dots').value = readWritten().dots === 1 ? '0' : '1'; setDuration(false, 'dots'); }   // TG: dotted toggles, double dot clears
        else if (e.key === '/') { const [n, d] = readWritten().tuplet, normal = n === 1 && d === 1;   // TG: normal <-> triplet
          ui('tuple-n').value = normal ? 3 : 1; ui('tuple-d').value = normal ? 2 : 1; setDuration(false, 'tuplet'); }
        else if (TECHNIQUE_KEYS[e.key]) runAction(TECHNIQUE_KEYS[e.key]);
        else if (e.key === ' ') host.transport(selection());
        else handled = false;
      } catch (err) { status(err.message || String(err)); }
      // A focused score must never let letters/digits rate or apply a tryout candidate.
      // F5–F8 returned above; their document capture handler remains the shared transport.
      e.stopPropagation(); if (handled) e.preventDefault();
    });
    listen(grid, 'click', e => {
      const b = e.target.closest('[data-at]'); if (!b) return;
      choose(b.dataset.at.split('/').map(Number), +(b.dataset.string || string), !b.dataset.string, true, e.ctrlKey || e.metaKey); root.focus();
    });
    // The TAB beat (and note) under the pointer, or null where alphaTab's staff handling applies.
    function scoreHit(e) {
      if (!api?.boundsLookup?.isFinished) return null;
      const surface = scoreHost.querySelector('.at-surface'); if (!surface) return null;
      const rect = surface.getBoundingClientRect(), scale = rect.width / surface.offsetWidth;
      const x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
      const candidates = [...tabHits, ...(ui('staff-mode').value === 'select' ? staffHits : staffHits.filter(h => isPercussion(view.score.tracks[h.rendered.track])))].filter(h => x >= h.bounds.barBounds.realBounds.x &&
        x <= h.bounds.barBounds.realBounds.x + h.bounds.barBounds.realBounds.w &&
        (y >= h.top - h.spacing / 2 && y <= h.bottom + h.spacing / 2 ||
          (h.bounds.notes || []).some(n => x >= n.noteHeadBounds.x && x <= n.noteHeadBounds.x + n.noteHeadBounds.w &&
            y >= n.noteHeadBounds.y && y <= n.noteHeadBounds.y + n.noteHeadBounds.h)));
      if (!candidates.length) return null; // Staff note hits retain alphaTab's handling.
      const noteHits = candidates.flatMap(h => (h.bounds.notes || []).map(n => ({h, n})))
        .filter(({n}) => x >= n.noteHeadBounds.x && x <= n.noteHeadBounds.x + n.noteHeadBounds.w &&
          y >= n.noteHeadBounds.y && y <= n.noteHeadBounds.y + n.noteHeadBounds.h);
      const noteHit = noteHits.find(({h}) => h.rendered.voice === voice) || noteHits[0];
      const active = candidates.filter(h => h.rendered.voice === voice);
      const hit = noteHit?.h || (active.length ? active : candidates)
        .reduce((a, b) => Math.abs(a.bounds.onNotesX - x) <= Math.abs(b.bounds.onNotesX - x) ? a : b);
      const ref = noteHit ? refs.get(noteHit.n.note.id) : beatRefs.get(hit.rendered.beat.id);
      return ref ? {ref, noteHit, hit, y} : null;
    }
    // Drag selection, as TuxGuitar's Start/UpdateDragSelection: past a small distance, every beat of the track
    // (both voices) from the pressed beat to the one under the pointer across written occurrences.
    let drag = null, selectionAnchor = null;
    listen(window, 'mousemove', e => {
      if (!drag || !(e.buttons & 1) || busy) return;
      if (!drag.active && Math.abs(e.clientX - drag.x) < 6) return;
      const found = scoreHit(e);
      if (!found || found.ref.track !== drag.track) return;
      drag.active = true;
      selectRange({occurrence: drag.occurrence, at: drag.at}, {occurrence: found.ref.occurrence, at: found.ref.at});
    });
    listen(window, 'mouseup', () => { drag = null; });
    // TuxGuitar's edition mouse mode (TGMouseClickAction, EditorKit.fillAddOrRemoveBeat/fillCreateNoteContext, pinned
    // 2c46e2a1): a staff click adds the clicked pitch at the nearest onset of the current voice, or removes it where it
    // already sounds, through the piano entry. Staff steps count from the clef's top line as this staff shows it
    // (treble F5, bass A3, alto G4, tenor E4). The optional TG written display is inverted below, including capo.
    const STAFF_TOP = {treble: [3, 5], bass: [5, 3], alto: [4, 4], tenor: [2, 4]}, SHARP_ORDER = [3, 0, 4, 1, 5, 2, 6];
    function staffPitch(steps, clef, fifths, natural) {
      const [i0, o0] = STAFF_TOP[clef] || STAFF_TOP.treble, index = ((i0 + steps) % 7 + 7) % 7;
      let value = 12 * (1 + o0 + Math.floor((i0 + steps) / 7)) + [0, 2, 4, 5, 7, 9, 11][index];
      const alter = fifths > 0 ? (SHARP_ORDER.slice(0, fifths).includes(index) ? 1 : 0) :
        fifths < 0 ? (SHARP_ORDER.slice(7 + fifths).includes(index) ? -1 : 0) : 0;
      if (natural) value += alter; else if (!alter) value += fifths >= 0 ? 1 : -1;
      return value;
    }
    try { const saved = localStorage.getItem('vt.staffMode'); if (saved) ui('staff-mode').value = saved; } catch (_) {}
    listen(ui('staff-mode'), 'change', () => { try { localStorage.setItem('vt.staffMode', ui('staff-mode').value); } catch (_) {} });
    listen(scoreHost, 'click', e => {
      const mode = ui('staff-mode').value;
      if (mode === 'select' || !view?.editable || busy || !api?.boundsLookup?.isFinished) return;
      const surface = scoreHost.querySelector('.at-surface'); if (!surface) return;
      const rect = surface.getBoundingClientRect(), scale = rect.width / surface.offsetWidth;
      const x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
      if (rawPreview()) return; // Tracker staff hits select source cells; they never enter notes.
      const items = renderedBeats.filter(r => !isPercussion(view.score.tracks[r.track]) && cmp(r.at, r.end) < 0).flatMap(rendered => {
        const renderer = api.renderer.instance.layout?.getRendererForBar('score', rendered.beat.voice.bar);
        const bounds = api.boundsLookup.findBeats(rendered.beat)?.[0];
        if (!renderer || !bounds) return [];
        const box = bounds.barBounds.visualBounds, real = bounds.barBounds.realBounds;
        if (x < real.x || x > real.x + real.w || y < box.y || y > box.y + box.h) return [];
        return [{rendered, bounds, real, top: box.y + renderer.getLineY(0), spacing: renderer.getLineY(1) - renderer.getLineY(0)}];
      });
      const mine = items.filter(i => i.rendered.voice === voice).sort((a, b) => a.bounds.onNotesX - b.bounds.onNotesX);
      if (!items.length) return;
      if (!mine.length) return status('No beat of the current voice in that measure.');
      const d = duration(readWritten()), candidates = [];
      mine.forEach((item, i) => {
        const ref = beatRefs.get(item.rendered.beat.id); if (!ref) return;
        const next = mine[i + 1]?.bounds.onNotesX ?? item.real.x + item.real.w, len = sub(item.rendered.end, item.rendered.at);
        const steps = item.rendered.beat.isRest ? Math.max(1, Math.floor(num(len) / num(d) + 1e-9)) : 1;
        for (let k = 0; k < steps; k++)
          candidates.push({ref, at: add(ref.at, rat(k * d[0], d[1])), x: item.bounds.onNotesX + (next - item.bounds.onNotesX) * k / steps});
      });
      if (!candidates.length) return;
      const best = candidates.reduce((a, b) => Math.abs(a.x - x) <= Math.abs(b.x - x) ? a : b);
      // Use the clicked track and measure's clef/key, including staff changes.
      const bar = mine[0].rendered.beat.voice.bar, clef = {[alphaTab.model.Clef.G2]: 'treble', [alphaTab.model.Clef.F4]: 'bass',
        [alphaTab.model.Clef.C3]: 'alto', [alphaTab.model.Clef.C4]: 'tenor'}[bar.clef];
      const pitch = staffPitch(Math.round(2 * (mine[0].top - y) / mine[0].spacing), clef, bar.keySignature || 0, mode === 'natural')
        + (viewPrefs.pitch === 'tuxguitar' ? (view.score.tracks[best.ref.track].capo || 0) - 12 : 0);
      e.preventDefault(); e.stopImmediatePropagation(); pauseFollow();
      focusRenderedTrack(best.ref.track);
      if (best.ref.order !== view.order) update({...view, order: best.ref.order, pattern: best.ref.pattern});
      choose(best.at, string, false, true);
      void enterPitch(pitch);
    }, {capture: true});
    listen(scoreHost, 'mousedown', e => {
      if (e.button !== 0 || busy) return;
      if (rawPreview()) {
        const surface = scoreHost.querySelector('.at-surface'); if (!surface) return;
        const rect = surface.getBoundingClientRect(), scale = rect.width / surface.offsetWidth;
        const x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
        // Resolve the actual notehead across every voice; a beat hit alone cannot
        // distinguish a chord's source channels or overlapping rhythmic voices.
        const hit = renderedBeats.flatMap(r => api.boundsLookup.findBeats(r.beat) || []).flatMap(b => b.notes || []).find(n => {
          const b = n.noteHeadBounds; return x >= b.x && x <= b.x + b.w && y >= b.y && y <= b.y + b.h;
        });
        const ref = hit && refs.get(hit.note.id);
        if (ref) { e.preventDefault(); e.stopImmediatePropagation(); selectRaw(ref.raw, true, ref.sources); root.focus({preventScroll: true}); }
        return;
      }
      const found = scoreHit(e); if (!found) return;
      const {ref, noteHit, hit, y} = found;
      e.preventDefault(); e.stopImmediatePropagation(); pauseFollow();
      const selectedVoice = noteHit ? ref.voice : voice;
      const extendFrom = ref.track === track && e.shiftKey && !e.ctrlKey && !e.metaKey ?
        (selectionAnchor && (selectedBeats.size || rangeSelection.length) ? selectionAnchor : {occurrence: occurrence(), at: [...at]}) : null;
      const changingOrder = ref.order !== view.order;
      focusRenderedTrack(ref.track);
      if (changingOrder) update({...view, order: ref.order, pattern: ref.pattern});
      voice = selectedVoice; ui('voice').value = voice;
      const lane = hit.staff ? string : Math.max(1, Math.min(spec().tuning.length, Math.round((y - hit.top) / hit.spacing) + 1));
      // Shift+press extends the selection to this beat (TuxGuitar's MouseKit: UpdateDragSelection, not StartDrag).
      choose(ref.at, noteHit ? ref.string : lane, false, true, e.ctrlKey || e.metaKey);
      if (changingOrder) navigationEcho = {...selection(), song: view.song, revision: view.revision};
      if (extendFrom) selectRange(extendFrom, {occurrence: ref.occurrence, at: ref.at});
      drag = e.ctrlKey || e.metaKey ? null : {track, at: [...(extendFrom?.at || ref.at)], occurrence: extendFrom?.occurrence || occurrence(), x: e.clientX, active: false};
      root.focus({preventScroll: true});
    }, {capture: true});
    listen(rawHost, 'click', e => {
      const b = e.target.closest('[data-raw-row]'); if (!b) return;
      const record = rawRecords().find(p => p.row === +b.dataset.rawRow && p.ch === +b.dataset.rawCh);
      if (record) selectRaw(record);
      root.focus();
    });
    function selectRaw(record, notify = true, sources = []) {
      if (rawPreview() && record.order != null && record.order !== view.order)
        update({...view, order: record.order, pattern: String(view.orders[record.order])});
      if (notify) navigationEcho = null;
      rawSelected = record; lastDigit = null; selectedBeats.clear(); selectedNotes.clear(); rangeSelection = []; selectionAnchor = null;
      if (record.track && view.score?.tracks[record.track]) { track = record.track; ui('track').value = track; }
      if (rawPreview()) at = rat(record.row, view.rows_per_beat || 4);
      else if (record.at) at = [...record.at];
      if (record.string) string = record.string;
      controls(); drawRaw(); markEditCaret();
      status(sources.length > 1 ? `Shared note · channels ${sources.map(p => p.ch + 1).join(', ')}. Select an individual channel to inspect its tracker cell.` : '');
      if (notify) {
        notifying = true;
        try { host.select({order: view.order, occurrence: occurrence(), pattern: view.pattern, row: record.row, ch: record.ch, source: 'raw'}); }
        finally { notifying = false; }
      }
    }
    function drawRaw() {
      rawHost.replaceChildren();
      const records = rawRecords();
      if (!records.length) return;
      rawHost.append(text('p', rawPreview() ?
        'Tracker staff preview — read only. Pitches match Pattern octave labels. Rhythm follows the row grid; lengths end at the next note/cut/release or pattern boundary. Effects, sample tuning and decay are not transcribed. Guitar TAB needs a configured track.' :
        'Existing Pattern notes — read only until explicitly adopted. Durations are notation hints from tracker boundaries.'));
      const table = document.createElement('table');
      for (const p of records) {
        const row = document.createElement('tr'), cell = document.createElement('td');
        const end = p.end_row == null ? '' : ` → ${Array.isArray(p.end_row) ? p.end_row[1] === 1 ? p.end_row[0] : p.end_row.join('/') : p.end_row}`;
        const button = text('button', `Row ${p.row}${end} · ch ${p.ch + 1} · ${pitchName(p.pitch + (rawPreview() ? 12 : 0))}${p.string ? ` · string ${p.string} fret ${p.fret}` : ' · unassigned'}`);
        button.type = 'button'; button.dataset.rawRow = p.row; button.dataset.rawCh = p.ch;
        if (p.occurrence != null) button.dataset.occurrence = p.occurrence;
        button.setAttribute('aria-pressed', String(rawSelected?.row === p.row && rawSelected?.ch === p.ch));
        cell.append(button); row.append(cell, text('td', p.reason)); table.append(row);
      }
      if (rawPreview()) {
        const details = document.createElement('details');
        details.append(text('summary', `Selected pattern ${view.pattern} · note list (${records.length})`), table); rawHost.append(details);
      } else rawHost.append(table);
    }

    function drawGrid() {
      grid.replaceChildren(); if (!spec()) { grid.append(text('p', 'Set up a guitar or bass track to start.')); return; }
      const list = beats(), points = list.map(b => b.at), drums = isPercussion(spec());
      if (!points.some(p => cmp(p, at) === 0)) points.push(at);
      points.sort(cmp);
      const table = document.createElement('table'), head = document.createElement('tr'); head.append(text('th', drums ? 'Lane' : 'String'));
      for (const p of points) { const th = document.createElement('th'), b = text('button', p[1] === 1 ? String(p[0]) : p.join('/')); b.type = 'button'; b.dataset.at = p.join('/'); b.title = 'Select chord at quarter-note position ' + p.join('/'); th.append(b); head.append(th); }
      table.append(head);
      spec().tuning.forEach((pitch, i) => {
        const tr = document.createElement('tr'); tr.append(text('th', drums ? `Lane ${i + 1}` : `${i + 1} · ${pitchName(pitch)}`));
        for (const p of points) {
          const beat = list.find(b => cmp(b.at, p) === 0), n = beat?.notes?.find(n => n.string === i + 1), td = document.createElement('td');
          const fret = n ? n.dead ? 'x' : n.fret == null ? '?' : String(n.fret) : '—';
          const b = text('button', n?.ghost ? `(${fret})` : fret); b.type = 'button';
          b.dataset.string = i + 1; b.dataset.at = p.join('/'); b.dataset.beat = beat?.id || ''; b.dataset.note = n?.id || '';
          b.setAttribute('aria-label', `${drums ? 'Lane' : 'String'} ${i + 1}, position ${p.join('/')}, ${n ? (drums ? 'drum key ' : 'fret ') + n.fret : 'empty'}`);
          if (n) {
            const techniques = [['staccato', 'Staccato'], ['palm_mute', 'Palm mute'], ['let_ring', 'Let ring'], ['fade_in', 'Fade-in (track expression)'], ['dead', 'Dead note'],
              ...tapSlapPop,
              ['vibrato', 'Vibrato'], ['slide', 'Slide'], ['bend', 'Bend'], ['tremolo_bar', 'Tremolo bar'],
              ['ghost', 'Ghost'], ['accent', 'Accent'], ['heavy_accent', 'Heavy accent'], ['hammer', 'Hammer-on/pull-off']].filter(([flag]) => n[flag]).map(([, label]) => label);
            if (n.harmonic) techniques.push(`${n.harmonic.type} harmonic`);
            if (n.trill) techniques.push(`Trill to fret ${n.trill.fret} (1/${n.trill.value})`);
            if (n.tremolo_picking) techniques.push(`Tremolo picking (1/${n.tremolo_picking.value})`);
            if (n.grace) techniques.push(graceLabel(n.grace, drums));
            if (beat.stroke) techniques.push(`Stroke ${beat.stroke.direction} · 1/${beat.stroke.value}`);
            b.title = [`Velocity: ${n.velocity ?? 'instrument default'}`, ...techniques, `${drums ? 'Drum key' : 'fret'} ${n.fret ?? 'unassigned'}`].join(' · ');
            if (techniques.length) b.dataset.techniques = techniques.join(',');
          }
          b.classList.toggle('selected', !ambiguousSelection && cmp(p, at) === 0 && (chosen === 'chord' || string === i + 1));
          b.classList.toggle('copy-selected', n ? !!selectedNotes.get(beat?.id)?.has(n.id) :
            selectedBeats.has(beat?.id) && !beat.notes.length && string === i + 1);
          b.setAttribute('aria-pressed', String(b.classList.contains('selected')));
          td.append(b); tr.append(td);
        }
        table.append(tr);
      }); grid.append(table);
      const unknown = list.flatMap(b => b.notes.filter(n => !Number.isInteger(n.string) || n.string < 1 || n.string > spec().tuning.length).map(n => `${n.id}: ${pitchName(n.pitch)} at ${b.at.join('/')}`));
      if (unknown.length) grid.append(text('p', 'Unassigned notes retained: ' + unknown.join('; '), 'vt-tab-warning'));
      markPlayhead();
    }

    function focusRenderedTrack(id) {
      if (id === track || !view?.score?.tracks[id]) return;
      track = id; ui('track').value = track;
      selectedBeats.clear(); selectedNotes.clear(); rangeSelection = []; selectionAnchor = null;
      string = Math.min(string, spec().tuning.length);
    }
    function engrave() {
      showViewPreferences();
      const preview = rawPreview();
      if ((!spec() && !preview) || !view?.pattern) { api?.destroy(); api = null; renderKey = ''; renderedBeats = []; tabHits = []; staffHits = []; scoreHost.replaceChildren(); root.querySelector('.vt-tab-meter').textContent = ''; return; }
      const key = JSON.stringify([view.score, view.orders, view.rows, view.pattern_names, view.tempo, view.tempos, view.lyrics, track, viewPrefs,
        preview ? [view.raw_positions, view.rows_per_beat, view.staff_groups, previewChannel] : null]); if (key === renderKey) return;
      renderKey = key;
      if (!window.alphaTab) { scoreHost.textContent = 'Score renderer unavailable. Local alphaTab assets must be loaded.'; return; }
      try {
        if (!api) {
          scoreHost.replaceChildren();
          api = new alphaTab.AlphaTabApi(scoreHost, {core: {engine: 'svg', useWorkers: false, includeNoteBounds: true,
            fontDirectory: '/web/', enableLazyLoading: false}, display: {layoutMode: alphaTab.LayoutMode.Page, effectBandPaddingBottom: 10},
            player: {enablePlayer: false, enableCursor: false, enableUserInteraction: false}});
          // These hit events fire with player interaction disabled; alphaTab handles its own canvas offsets.
          const hit = (ref, chord) => {
            if (!ref || busy) return;
            if (ref.raw) { selectRaw(ref.raw, true, ref.sources);
              root.focus({preventScroll: true}); return; }
            pauseFollow();
            focusRenderedTrack(ref.track);
            const selectedVoice = chord && isPercussion(spec()) ? voice : ref.voice;
            if (ref.order !== view.order) update({...view, order: ref.order, pattern: ref.pattern});
            voice = selectedVoice; ui('voice').value = voice;
            choose(ref.at, ref.string || string, chord && !isPercussion(spec())); root.focus({preventScroll: true});
          };
          api.beatMouseDown.on(b => hit(beatRefs.get(b.id), true));
          api.noteMouseDown.on(n => hit(refs.get(n.id), false));
          api.error.on(e => status(`Score rendering failed: ${e.message || e}`));
          // alphaTab reuses surface children by index. Keep our overlays out
          // while it replaces SVG parts (including its attribution footer).
          api.renderStarted.on(() => {
            editCaret.remove(); scoreCursor.remove();
            scoreHost.querySelectorAll('.vt-tab-selection').forEach(el => el.remove());
          });
          let layoutErrorText = '';
          api.postRenderFinished.on(() => {
            const error = textLayoutError(api), surface = scoreHost.querySelector('.at-surface');
            if (surface) surface.hidden = !!error;
            if (error) { status(error); layoutErrorText = error; tabHits = []; staffHits = []; scoreCursor.hidden = editCaret.hidden = true; return; }
            if (layoutErrorText && root.querySelector('.vt-tab-status').textContent === layoutErrorText) status('');
            layoutErrorText = '';
            scoreHost.dataset.bars = api.score.masterBars.length; buildTabHits(); markEditCaret(); markPlayhead();
          });
        }
        api.settings.display.layoutMode = viewPrefs.layout === 'horizontal' ? alphaTab.LayoutMode.Horizontal : alphaTab.LayoutMode.Page;
        api.settings.display.scale = viewPrefs.scale / 100;
        api.settings.notation.elements.set(alphaTab.NotationElement.EffectDynamics, viewPrefs.dynamics);
        // Every rhythm is equally important in a read-only merged staff.
        api.settings.display.resources.secondaryGlyphColor = preview ? api.settings.display.resources.mainGlyphColor :
          new alphaTab.Settings().display.resources.secondaryGlyphColor;
        api.updateSettings();
        Object.assign(scoreHost.dataset, {layout: viewPrefs.layout, scale: viewPrefs.scale, notation: viewPrefs.notation});
        if (preview) { engraveRaw(); return; }
        delete scoreHost.dataset.previewNotes;
        const score = notationScore();
        const timeline = printTimeline(view), ranges = timeline.ranges;
        // TuxGuitar's measure errors for this track (gaps and voices that end early), counted here, listed on hover.
        const errors = (view.measure_errors || []).filter(e => e.track === track), said = {gap: 'has a gap', short: 'ends early', long: 'is too long (overfull)'};
        root.querySelector('.vt-tab-meter').title = errors.map(e => `Bar ${e.bar}, voice ${e.voice + 1}: ${e.errors.map(x => said[x]).join(' and ')}`).join('\n');
        root.querySelector('.vt-tab-meter').textContent = `${spec()?.capo ? `Capo ${spec().capo} · ` : ''}${errors.length ? `${errors.length} measure error${errors.length > 1 ? 's' : ''} · ` : ''}Full written score · ${view.orders.length} order occurrences · ${ranges.filter(r => r.authored).length} authored measures · ${ranges.length} displayed bars` +
          (ranges.some(r => !r.authored) ? ' · unmetered display groups are not authored measures' : '');
        refs = new Map(); beatRefs = new Map(); renderedBeats = []; tabHits = []; staffHits = []; scoreCursor.hidden = true; editCaret.hidden = true;
        const reference = (id, original, v, note, start) => {
          const oid = original?.sourceOccurrence || [...timeline.offsets].filter(([, offset]) => cmp(offset, start) <= 0).at(-1)?.[0];
          const order = view.score.order_ids.indexOf(oid);
          return {track: id, order, occurrence: oid, pattern: String(view.orders[order]), beat: original?.id,
            note: note?.sourceNote, at: original?.sourceAt || sub(start, timeline.offsets.get(oid)), voice: v, string: note?.string};
        };
        const displayed = viewPrefs.multitrack ? Object.keys(view.score.tracks) : [track];
        scoreHost.dataset.tracks = displayed.join(',');
        const compact = viewPrefs.compact && displayed.length === 1;
        scoreHost.dataset.compact = String(compact);
        if (compact) compactScores.add(score);
        for (const id of displayed) {
          const t = notationTrack(score, id, view.score.tracks[id], ranges, timeline.source.filter(b => b.track === id), timeline.tieTargets,
            (beat, original, start, end, v) => {
              const ref = reference(id, original, v, null, start);
              renderedBeats.push({track: id, beat, at: start, end, voice: v, sourceBeat: original?.id, occurrence: ref.occurrence});
              beatRefs.set(beat.id, ref);
            }, (note, originalNote, original, v) => refs.set(note.id, reference(id, original, v, originalNote)));
          const drums = isPercussion(view.score.tracks[id]), staff = t.staves[0];
          staff.displayTranspositionPitch = !drums && viewPrefs.pitch === 'tuxguitar' ? (view.score.tracks[id].capo || 0) - 12 : 0;
          staff.showStandardNotation = drums || viewPrefs.notation !== 'tab';
          staff.showTablature = !drums && viewPrefs.notation !== 'staff';
          for (const chord of staff.chords?.values() || []) {
            chord.showName = !!chord.name && viewPrefs.chordNames;
            chord.showDiagram = viewPrefs.chordDiagrams;
          }
        }
        notationTempos(score, ranges, view);
        ui('tempo-warning').textContent = score.tempoUnitWarnings.join(' ');
        ui('tempo-warning').hidden = !score.tempoUnitWarnings.length;
        score.finish(api.settings); spaceChordDiagrams(api, score);
        delete scoreHost.dataset.bars; api.renderScore(score, score.tracks.map(t => t.index));
      } catch (e) { status(`Score rendering failed: ${e.message || e}`); }
    }
    function engraveRaw() {
      const score = notationScore(), timeline = trackerTimeline(view, previewChannel);
      previewOccurrences = timeline.occurrences;
      refs = new Map(); beatRefs = new Map(); renderedBeats = []; tabHits = []; staffHits = [];
      scoreCursor.hidden = editCaret.hidden = true;
      for (const [id, spec] of Object.entries(timeline.tracks)) {
        const t = notationTrack(score, id, spec, timeline.ranges, timeline.source.filter(b => b.track === id), timeline.tieTargets,
          (b, original, start, end, v) => {
            const occurrence = previewOccurrences.find(o => cmp(o.from, start) <= 0 && cmp(start, o.to) < 0);
            renderedBeats.push({track: id, beat: b, at: start, end, voice: v, order: occurrence?.order});
            if (original) beatRefs.set(b.id, {raw: original.raw});
          }, (n, note) => refs.set(n.id, {raw: note.raw, sources: note.sources}));
        t.staves[0].showStandardNotation = true; t.staves[0].showTablature = false;
      }
      Object.assign(scoreHost.dataset, {notation: 'staff', tracks: timeline.channels.join(','), previewNotes: timeline.attacks,
        previewHeads: timeline.heads, previewStaves: score.tracks.length, previewOrders: previewOccurrences.length});
      root.querySelector('.vt-tab-meter').textContent = `Full tracker song · ${previewOccurrences.length} order occurrences · ${timeline.ranges.length} bars · ${timeline.attacks} source attacks · ${timeline.heads} noteheads · ${score.tracks.length} staves · ${timeline.perBeat} rows per quarter`;
      ui('tempo-warning').hidden = true;
      score.finish(api.settings); delete scoreHost.dataset.bars; api.renderScore(score, score.tracks.map(t => t.index));
    }
    function buildTabHits() {
      if (rawPreview()) { tabHits = []; staffHits = []; return; }
      // Pinned alphaTab 1.8.4: findBeats returns score then TAB bounds (the
      // default renderer order). getLineY is also used to paint each TAB line.
      // Workers are disabled above, so the renderer instance owns this layout.
      tabHits = renderedBeats.filter(r => cmp(r.at, r.end) < 0).flatMap(rendered => {
        const renderer = api.renderer.instance.layout?.getRendererForBar('tab', rendered.beat.voice.bar);
        const bounds = api.boundsLookup.findBeats(rendered.beat)?.at(-1);
        if (!renderer || !bounds) return [];
        const top = bounds.barBounds.visualBounds.y + renderer.getLineY(0);
        const spacing = renderer.getLineY(1) - renderer.getLineY(0);
        return [{rendered, bounds, top, spacing, bottom: top + spacing * (view.score.tracks[rendered.track].tuning.length - 1)}];
      });
      staffHits = renderedBeats.filter(r => cmp(r.at, r.end) < 0).flatMap(rendered => {
        const renderer = api.renderer.instance.layout?.getRendererForBar('score', rendered.beat.voice.bar);
        const bounds = api.boundsLookup.findBeats(rendered.beat)?.[0];
        if (!renderer || !bounds) return [];
        const top = bounds.barBounds.visualBounds.y + renderer.getLineY(0), spacing = renderer.getLineY(1) - renderer.getLineY(0);
        return [{rendered, bounds, top, spacing, bottom: top + spacing * 4, staff: true}];
      });
    }
    function markSelection() {
      scoreHost.querySelectorAll('.vt-tab-selection').forEach(el => el.remove());
      const surface = scoreHost.querySelector('.at-surface'); if (!surface || !view || !rangeSelection.length && selectedBeats.size < 2) return;
      const tabbed = new Set(tabHits.map(h => h.rendered));
      for (const h of [...tabHits, ...staffHits.filter(h => !tabbed.has(h.rendered))]) {
        if (h.rendered.track !== track) continue;
        if (rangeSelection.length ? !rangeSelection.some(g => g.occurrence === h.rendered.occurrence && g.beats.includes(h.rendered.sourceBeat)) :
            h.rendered.occurrence !== occurrence() || !selectedBeats.has(h.rendered.sourceBeat)) continue;
        const box = h.bounds.visualBounds, mark = document.createElement('div');
        mark.className = 'vt-tab-selection'; mark.dataset.track = track; mark.dataset.beat = h.rendered.sourceBeat; mark.dataset.occurrence = h.rendered.occurrence;
        Object.assign(mark.style, {left: box.x + 'px', width: Math.max(4, box.w) + 'px', top: h.top - h.spacing / 2 + 'px',
          height: h.bottom - h.top + h.spacing + 'px'});
        surface.append(mark);
      }
    }
    function markEditCaret() {
      markSelection();
      editCaret.hidden = true;
      if (!view || rawSelected || ambiguousSelection) return;
      const origin = (view.occurrences || []).find(o => o.id === occurrence())?.at;
      if (!origin) return;
      const absolute = add(origin, at);
      const staffCaret = isPercussion(spec()) || viewPrefs.notation === 'staff';
      const candidates = (staffCaret ? renderedBeats.filter(rendered => rendered.track === track).map(rendered => {
        const bounds = api?.boundsLookup?.findBeat(rendered.beat);
        if (!bounds) return null;
        const note = bounds.notes?.find(n => refs.get(n.note.id)?.string === string)?.noteHeadBounds;
        return {rendered, bounds, top: note ? note.y + note.h / 2 : bounds.barBounds.visualBounds.y + bounds.barBounds.visualBounds.h / 2, spacing: 16};
      }).filter(Boolean) : tabHits).filter(h => h.rendered.track === track && cmp(h.rendered.at, absolute) <= 0 && cmp(h.rendered.end, absolute) > 0);
      const hit = candidates.find(h => h.rendered.voice === voice) || candidates[0];
      const surface = scoreHost.querySelector('.at-surface'); if (!hit || !surface) return;
      surface.append(editCaret);
      editCaret.style.left = hit.bounds.onNotesX + 'px';
      editCaret.style.top = hit.top + (staffCaret ? 0 : (string - 1) * hit.spacing) + 'px';
      editCaret.style.height = Math.max(12, hit.spacing) + 'px';
      Object.assign(editCaret.dataset, {track, occurrence: occurrence(), pattern: view.pattern, voice, at: at.join('/'),
        string, bar: hit.rendered.beat.voice.bar.index});
      editCaret.hidden = false;
      if (revealCaret) {
        const caret = editCaret.getBoundingClientRect(), container = scrollHost.getBoundingClientRect();
        if (caret.top < container.top || caret.bottom > container.bottom || caret.left < container.left || caret.right > container.right)
          editCaret.scrollIntoView({block: 'nearest', inline: 'nearest'});
        revealCaret = false;
      }
    }
    function revealEditCaret() { revealCaret = true; markEditCaret(); }
    function update(next) {
      if (destroyed) return;
      const changedPattern = view && (view.pattern !== next.pattern || view.order !== next.order), changedSong = view && next.song !== view.song;
      if (changedPattern || changedSong || view?.revision !== next.revision) {
        if (rangeSelection.length) { selectedBeats.clear(); selectedNotes.clear(); selectionAnchor = null; }
        rangeSelection = [];
      }
      view = next;
      clock = nativeScoreClock(view);
      if (navigationEcho && (navigationEcho.song !== view.song || navigationEcho.revision !== view.revision || navigationEcho.order !== view.order)) navigationEcho = null;
      const names = Object.keys(view.score?.tracks || {}); if (!names.includes(track)) track = names[0] || '';
      ui('track').replaceChildren(...names.map(name => { const o = text('option', view.score.tracks[name].name || name); o.value = name; return o; })); ui('track').value = track;
      if (rawPreview()) {
        if (changedSong || previewChannel >= view.channels.length) previewChannel = -1;
        ui('track').replaceChildren(...[-1, -2, ...view.channels.keys()].map(ch => {
          const option = text('option', ch === -1 ? 'All parts (by sound)' : ch === -2 ? 'All channels (separate)' : `${ch + 1} · ${view.channels[ch]}`); option.value = ch; return option;
        })); ui('track').value = previewChannel;
      }
      root.querySelector('[data-action="quick-previous"]').textContent = rawPreview() ? '◀ Pattern' : '◀ Bar';
      root.querySelector('[data-action="quick-next"]').textContent = rawPreview() ? 'Pattern ▶' : 'Bar ▶';
      if (changedPattern || changedSong || cmp(at, end()) >= 0) { at = [0, 1]; pending = ''; chosen = null; lastDigit = null; rawSelected = null; selectedBeats.clear(); selectedNotes.clear(); }
      selectedBeats = new Set([...selectedBeats].filter(id => allBeats().some(b => b.track === track && b.id === id)));
      if (changedSong && !clipboard?.track_specs) { clipboard = null; clipboardSong = null; }
      if (rawSelected) rawSelected = rawRecords().find(p => p.row === rawSelected.row && p.ch === rawSelected.ch) || null;
      const b = current(); if (b) written = clone(b.written);
      root.querySelector('.vt-tab-diagnostics').textContent = [...new Set([...(view.diagnostics || []),
        ...(view.lyrics?.errors || [])].map(d => typeof d === 'string' ? d : d.message || JSON.stringify(d)))].join(' · ');
      drawMarkers(); controls(); drawGrid(); drawRaw(); drawMeasures(); engrave(); markEditCaret();
    }
    function setSelection(s) {
      if (!view || !s || notifying || s.pattern != null && s.pattern !== view.pattern) return;
      if (s.order != null && s.order !== view.order) return;
      if (s.occurrence != null && s.occurrence !== occurrence()) return;
      const ch = s.channel ?? s.ch;
      if (rawPreview()) {
        if (s.row != null) {
          const [n, d] = rowPair(s.row);
          at = rat(n, d * (view.rows_per_beat || 4));
          rawSelected = rawRecords().find(p => sameRow(p.row, s.row) && p.ch === ch) || null;
          controls(); drawRaw(); markEditCaret();
        }
        return; // A tracker rest has no native track/beat selection to synchronize.
      }
      // The host refreshes a changed order asynchronously and echoes only its
      // tracker row/channel. Preserve the exact TAB voice/string on that echo,
      // including blank beats above a raw note; navigation must not select it.
      if (navigationEcho) {
        const selected = navigationEcho;
        if (sameRow(s.row, selected.row) && ch === selected.channel &&
            (!s.track || s.track === selected.track) && (s.voice == null || s.voice === selected.voice)) {
          track = selected.track; voice = selected.voice; ui('track').value = track; ui('voice').value = voice;
          if (!rangeSelection.length) { navigationEcho = null; choose(selected.at, selected.string, false, false); }
          engrave(); return;
        }
        navigationEcho = null;
      }
      if (ch != null && !s.track) track = Object.keys(view.score?.tracks || {}).find(k => view.score.tracks[k].channels.includes(ch)) || track;
      if (s.track && view.score.tracks[s.track]) track = s.track;
      if (s.voice != null) voice = s.voice;
      const precise = s.id || s.beat || s.note || s.track || s.at;
      const links = (view.positions || []).filter(p => p.kind === 'note' && atOccurrence(p, view, view.pattern) &&
        (s.id ? p.id === s.id : s.note ? p.note === s.note : !precise && ch != null && p.ch === ch && sameRow(p.row, s.row)));
      if (links.length > 1) {
        // An address alone cannot identify a written voice. Keep the current
        // TAB focus until the host sends a source ID or the user selects here.
        ambiguousSelection = true; selectedBeats.clear(); selectedNotes.clear(); rangeSelection = []; selectionAnchor = null; chosen = null;
        controls(); drawGrid(); markEditCaret();
        status('Choose a source note in Pattern or ROLL to select an overlapping voice.');
        return;
      }
      const link = links[0];
      const raw = !precise && !link && ch != null && s.row != null ? rawRecords().find(p => sameRow(p.row, s.row) && p.ch === ch) : null;
      if (raw) { selectRaw(raw, false); return; }
      let b = (s.beat || link?.beat) && allBeats().find(b => b.id === (s.beat || link?.beat));
      if (!b && s.note) b = allBeats().find(b => b.notes.some(n => n.id === s.note));
      if (b) { track = b.track; voice = b.voice; }
      const p = b?.at || s.at || (s.row != null ? (Array.isArray(s.row) ? rat(s.row[0] * rowStep()[0], s.row[1] * rowStep()[1]) : rat(s.row * rowStep()[0], rowStep()[1])) : at);
      const ns = s.string || link?.string || b?.notes.find(n => n.id === s.note)?.string || (ch != null ? spec()?.channels.indexOf(ch) + 1 : string) || string;
      ui('track').value = track; ui('voice').value = voice; choose(p, ns, s.chord, false); engrave();
    }
    function markPlayhead() {
      const preview = rawPreview(), playedOrder = playhead?.order ?? playhead?.o;
      const previewOccurrence = preview ? previewOccurrences.find(o => o.order === playedOrder) : null;
      const playedOccurrence = preview ? (previewOccurrence ? `tracker-${playedOrder}` : null) : view?.score?.order_ids?.[playedOrder];
      const matches = playedOccurrence && (playhead.occurrence == null || playhead.occurrence === playedOccurrence);
      const playedPattern = matches ? String(view.orders[playedOrder]) : null;
      const playedBeats = matches && !preview ? resolvedBeats(view, playedPattern, playedOccurrence).filter(b => b.track === track) : [];
      const playedStep = view?.score?.patterns?.[playedPattern]?.row_step || view?.row_step || [1, 1];
      const visit = playhead?.visit, plan = playhead?.playbackPlan;
      if (plan !== playbackClockPlan) { playbackClockPlan = plan; playbackClock = plan ? nativeScoreClock(plan) : null; }
      const row = playhead?.exactRow ?? playhead?.row;
      const p = matches ? preview ? (row != null ? rat(rowPair(row)[0], rowPair(row)[1] * (view.rows_per_beat || 4)) : null) :
        playhead.at || (row != null ? rat(rowPair(row)[0] * playedStep[0], rowPair(row)[1] * playedStep[1]) : null) : null;
      const writtenOrigin = preview ? previewOccurrence?.from : (view?.occurrences || []).find(o => o.id === playedOccurrence)?.at;
      const origin = visit ? sub(visit.at, visit.source_from) : writtenOrigin;
      const factorQ = playhead?.factorQ ?? 65536;
      const framed = !preview && matches && origin && (!visit || playbackClock) && Number.isSafeInteger(playhead.scoreFrame) &&
        Number.isSafeInteger(playhead.sampleRate) && playhead.sampleRate > 0 && Number.isSafeInteger(view.tempo) && view.tempo > 0 &&
        Number.isSafeInteger(factorQ) && factorQ > 0;
      const frameAt = at => {
        const n = BigInt(origin[0]) * BigInt(at[1]) + BigInt(at[0]) * BigInt(origin[1]);
        const d = BigInt(origin[1]) * BigInt(at[1]);
        return (visit ? playbackClock : clock).frameAt([n, d], playhead.sampleRate, factorQ);
      };
      // Compare the same rounded boundaries that dispatch native events. The
      // continuous musical clock can be half a frame before an audible onset.
      const contains = (from, to) => {
        if (visit) {
          if (Number.isSafeInteger(playhead.scoreFrame) && !playbackClock) return false;
          if (cmp(from, visit.source_from) < 0) from = visit.source_from;
          if (cmp(to, visit.source_to) > 0) to = visit.source_to;
          if (cmp(from, to) >= 0) return false;
        }
        return framed ? frameAt(from) <= playhead.scoreFrame && frameAt(to) > playhead.scoreFrame :
          p && cmp(from, p) <= 0 && cmp(to, p) > 0;
      };
      const strokeContains = (beat, note) => {
        if (!origin) return false;
        const positions = visit ? plan?.positions || [] : view?.positions || [];
        return positions.some(position => position.kind !== 'beat' && position.note === note.id &&
          (visit ? position.source_occurrence === playedOccurrence : position.occurrence === playedOccurrence) &&
          contains(sub(position.sounding_start || position.at, origin), sub(position.sounding_end || position.end, origin)));
      };
      const active = playedBeats.filter(b => b.stroke && b.notes.length ? b.notes.some(n => strokeContains(b, n)) :
        contains(b.at, add(b.at, duration(b.written)))).map(b => b.id);
      if (board.open || piano.open) {
        boardPlayback = matches ? resolvedBeats(view, playedPattern, playedOccurrence).filter(b => b.track === track &&
          contains(b.at, add(b.at, duration(b.written)))) : null;
        drawFretboard(); drawPiano();
      }
      for (const button of grid.querySelectorAll('[data-beat]')) {
        const beat = beats().find(b => b.id === button.dataset.beat), note = beat?.notes?.find(n => n.id === button.dataset.note);
        button.classList.toggle('playing', playedOrder === view?.order &&
          (beat?.stroke && note ? strokeContains(beat, note) : active.includes(button.dataset.beat)));
      }
      scoreCursor.hidden = true;
      const candidates = writtenOrigin ? renderedBeats.filter(b => (preview || b.track === track) && cmp(b.at, b.end) < 0 &&
        (b.occurrence === playedOccurrence && playedBeats.find(source => source.id === b.sourceBeat)?.stroke ?
          active.includes(b.sourceBeat) : contains(sub(b.at, writtenOrigin), sub(b.end, writtenOrigin)))) : [];
      // An empty editing voice must not hide the whole part's playback cursor.
      const rendered = preview ? candidates.sort((a, b) => cmp(b.at, a.at))[0] : candidates.find(b => b.voice === voice) || candidates[0];
      const staves = rendered && api?.boundsLookup?.findBeats(rendered.beat), bounds = staves?.[0], surface = scoreHost.querySelector('.at-surface');
      if (bounds && surface) {
        // Bounds are relative to alphaTab's rendering surface, including rests.
        // The shared tracker playhead drives this beat-aligned marker; no second player.
        surface.append(scoreCursor);
        scoreCursor.style.left = bounds.onNotesX + 'px';
        if (preview) {
          // Move on each tracker row, including long notes and empty measures.
          const bar = rendered.beat.voice.bar.index;
          const absolute = add(writtenOrigin, p);
          const next = renderedBeats.filter(b => b.beat.voice.bar.index === bar && cmp(b.at, absolute) > 0)
            .sort((a, b) => cmp(a.at, b.at))[0];
          const to = next?.at || rendered.end, nextBounds = next && api.boundsLookup.findBeats(next.beat)?.[0];
          const right = nextBounds?.onNotesX ?? bounds.barBounds.visualBounds.x + bounds.barBounds.visualBounds.w;
          const fraction = num(sub(absolute, rendered.at)) / num(sub(to, rendered.at));
          scoreCursor.style.left = bounds.onNotesX + Math.max(0, Math.min(1, fraction)) * (right - bounds.onNotesX) + 'px';
          scoreCursor.dataset.row = num(p) * (view.rows_per_beat || 4);
          scoreCursor.dataset.order = playedOrder;
          scoreCursor.dataset.pattern = playedPattern;
        }
        // Standard notation and TAB: from the top of the first staff to the bottom of the last.
        const visibleStaves = preview ? candidates.flatMap(b => api.boundsLookup.findBeats(b.beat) || []) : staves;
        const boxes = visibleStaves.map(b => b.barBounds?.visualBounds).filter(v => v && Number.isFinite(v.y) && Number.isFinite(v.h));
        if (!boxes.length) boxes.push(bounds.barBounds.visualBounds);
        const top = Math.min(...boxes.map(v => v.y)), bottom = Math.max(...boxes.map(v => v.y + v.h));
        scoreCursor.style.top = top + 'px';
        scoreCursor.style.height = bottom - top + 'px';
        scoreCursor.dataset.at = sub(rendered.at, writtenOrigin).join('/');
        scoreCursor.dataset.scoreAt = rendered.at.join('/'); scoreCursor.hidden = false;
        scoreCursor.dataset.occurrence = playedOccurrence;
        scoreCursor.dataset.track = rendered.track;
        scoreCursor.dataset.bar = rendered.beat.voice.bar.index;
        if (canFollowPlayback()) {
          const rect = scoreCursor.getBoundingClientRect(), container = root.closest('.main')?.getBoundingClientRect();
          const clip = scoreHost.getBoundingClientRect();
          const left = container && (preview ? Math.max(clip.left, container.left) + 8 : container.left);
          const right = container && (preview ? Math.min(clip.right, container.right) - 8 : container.right);
          if (container && preview && viewPrefs.layout === 'horizontal') {
            if (rect.left < left || rect.right > right) scoreHost.scrollLeft += rect.left - (left + right) / 2;
            // Preserve the user's vertical channel position while any of the marker is visible.
            if (rect.bottom < container.top || rect.top > container.bottom)
              scoreCursor.scrollIntoView({block: 'nearest', inline: 'nearest'});
          } else if (container && (rect.top < container.top || (preview ? rect.top : rect.bottom) > container.bottom || rect.left < left || rect.right > right))
            scoreCursor.scrollIntoView({block: preview ? 'start' : 'center', inline: preview ? 'center' : 'nearest'});
        }
      }
    }
    function setPlayhead(p) {
      playhead = p;
      markPlayhead(); commandControls(); lyricsControls();
      const label = view ? `${rawPreview() ? 'Selected' : 'Editing'} ${view.order + 1}/${view.orders.length} · ${view.pattern}${occurrence() ? ' · ' + occurrence() : ''}` +
        (p ? ` · Playing ${p.o + 1}/${view.orders.length}${p.pass ? ` · pass ${p.pass}` : ''}` : '') : '';
      if (ui('order-context').textContent !== label) ui('order-context').textContent = label;
    }
    const following = () => ui('follow').checked;
    const pauseFollow = order => {
      ui('follow').checked = false;
      revealCaret = false;
      if (order != null && view && order !== view.order && view.orders[order] != null)
        update({...view, order, pattern: String(view.orders[order])});
    };
    const canFollowPlayback = () => following() && host.followAllowed?.() !== false && !busy && !root.querySelector('form:not([hidden])') &&
      !document.activeElement?.matches('input:not([type=checkbox]),select,textarea,[contenteditable=true]');
    function destroy() { destroyed = true; abort.abort(); api?.destroy(); root.replaceChildren(); root.classList.remove('vt-tab'); }
    return {update, setSelection, setPlayhead, pauseFollow, enterPitch, enterMatrix, selectTrack, get track() { return track; }, destroy};
  }
  function trackerTimeline(view, previewChannel = -1) {
    const ranges = [], perBeat = view.rows_per_beat || 4;
    const records = [], occurrences = []; let end = [0, 1];
    // Expand the written order, including repeated patterns, exactly once per occurrence.
    // Unsequenced patterns are not part of the song; playback loops reuse their written location.
    view.orders.forEach((name, order) => {
      const pattern = String(name), rows = view.rows[view.pattern_names.indexOf(pattern)];
      if (!rows) return;
      const from = end, firstBar = ranges.length; end = add(from, rat(rows, perBeat));
      occurrences.push({order, pattern, from, to: end});
      displayGroups(ranges, from, end);
      ranges[firstBar].marker = {title: `${order + 1} · ${pattern}`};
      for (const p of (view.raw_positions || []).filter(p => p.pattern_name === pattern))
        records.push({...p, order, offset: from, rows});
    });
    const channels = previewChannel < 0 ? [...new Set(records.map(p => p.ch))].sort((a, b) => a - b) : [previewChannel];
    const tracks = {}, allSource = [], tieTargets = new Set();
    const separate = (channels.length ? channels : [0]).map(ch => ({name: `${ch + 1} · ${view.channels[ch]}`, channels: [ch]}));
    const groups = previewChannel === -1 && view.staff_groups?.length ? view.staff_groups : separate;
    let heads = 0;
    for (const group of groups) {
      // Identical spans share a chord. Exact unisons share a notehead, retaining
      // every source cell. Independent rhythms use interval-packed voices.
      const spans = new Map(), ends = [], parts = [];
      for (const p of records.filter(p => group.channels.includes(p.ch))) {
        const key = `${p.order}:${p.row}:${p.boundary_row ?? p.rows}`;
        if (!spans.has(key)) spans.set(key, {at: add(p.offset, rat(p.row, perBeat)), length: rat((p.boundary_row ?? p.rows) - p.row, perBeat), records: []});
        spans.get(key).records.push(p);
      }
      for (const span of [...spans.values()].sort((a, b) => cmp(a.at, b.at))) {
        let v = ends.findIndex(end => cmp(end, span.at) <= 0); if (v < 0) v = ends.length;
        ends[v] = add(span.at, span.length);
        // Keep busy groups readable: at most two independent rhythms per staff.
        const part = Math.floor(v / 2); parts[part] ||= {source: [], ties: new Set()};
        const pitches = new Map();
        for (const p of span.records) { if (!pitches.has(p.pitch)) pitches.set(p.pitch, []); pitches.get(p.pitch).push(p); }
        heads += pitches.size;
        let at = span.at;
        spellSpan(span.length).forEach((written, i) => {
          const notes = [...pitches.values()].map(sources => {
            const p = sources[0], id = `preview-${p.order}-${p.ch}-${p.row}-${i}`;
            if (i) parts[part].ties.add(id);
            // Match Pattern's IT octave labels, not a sample's concert tuning.
            return {id, pitch: p.pitch + 12, raw: p, sources};
          });
          parts[part].source.push({id: notes[0].id, raw: span.records[0], at, written, voice: v % 2, notes});
          at = add(at, duration(written));
        });
      }
      if (!parts.length) parts.push({source: [], ties: new Set()});
      for (const [part, {source, ties}] of parts.entries()) {
        const id = `channel-${group.channels[0]}${part ? ':' + part : ''}`;
        const name = group.name + (group.channels.length > 1 ? ` · Ch ${group.channels.map(ch => ch + 1).join(', ')}` : '') + (parts.length > 1 ? ` · part ${part + 1}` : '');
        const pitches = source.flatMap(b => b.notes.map(n => n.pitch)), average = pitches.reduce((a, b) => a + b, 0) / pitches.length;
        tracks[id] = {name, tuning: [], clef: average < 60 ? 'bass' : 'treble'};
        for (const beat of source) allSource.push({...beat, track: id});
        for (const target of ties) tieTargets.add(target);
      }
    }
    return {raw: true, ranges, channels, occurrences, heads, tracks, source: allSource, tieTargets,
      attacks: records.filter(p => channels.includes(p.ch)).length, perBeat};
  }

  function printTimeline(view) {
    if (!view.score || !Object.keys(view.score.tracks).length) throw new Error('Set up and author a score before printing.');
    const offsets = new Map(), source = []; let end = [0, 1];
    const identity = (occurrence, note) => JSON.stringify([occurrence, note]);
    view.orders.forEach((name, index) => {
      name = String(name);
      const occurrence = view.score.order_ids[index], rows = view.rows[view.pattern_names.indexOf(name)];
      const step = view.score.patterns[name]?.row_step || view.row_step;
      if (!occurrence || !rows || !step) throw new Error('An order occurrence has no printable timing.');
      offsets.set(occurrence, end);
      for (const b of resolvedBeats(view, name, occurrence)) source.push({...b, sourcePattern: name, sourceAt: b.at, at: add(end, b.at),
        notes: b.notes.map(n => ({...n, sourceNote: n.id, id: identity(occurrence, n.id)}))});
      end = add(end, rat(rows * step[0], step[1]));
    });
    const position = p => { if (!offsets.has(p.occurrence)) throw new Error('A measure references a missing occurrence.'); return add(offsets.get(p.occurrence), p.at); };
    const authored = (view.score.measures || []).map(m => ({id: m.id, from: position(m.from), to: position(m.to), meter: m.meter, swing: m.swing, tempo_unit: m.tempo_unit, repeat_open: m.repeat_open, repeat_close: m.repeat_close, endings: m.endings, double_bar: m.double_bar, marker: m.marker, staff: m.staff, authored: true})).sort((a, b) => cmp(a.from, b.from));
    const ranges = []; let cursor = [0, 1];
    for (const r of authored) {
      if (cmp(r.from, cursor) < 0 || cmp(r.to, r.from) <= 0 || cmp(r.to, end) > 0) throw new Error('Authored measures overlap or lie outside the song.');
      displayGroups(ranges, cursor, r.from); ranges.push(r); cursor = r.to;
    }
    displayGroups(ranges, cursor, end);
    if (!ranges.length) throw new Error('The score has no order occurrences to print.');
    const activeStaff = {};
    for (const range of ranges) {
      for (const [id, change] of Object.entries(range.staff || {})) activeStaff[id] = {...activeStaff[id], ...change};
      range.staff = clone(activeStaff);
    }
    return {source, ranges, offsets, tieTargets: new Set((view.score.ties || []).map(t => identity(t.to.occurrence, t.to.note)))};
  }

  function mountPrint(root, snapshot, {saveImage, previewChannel = -1} = {}) {
    registerLyricsEngraving();
    const view = clone(snapshot), abort = new AbortController();
    let api = null, generation = 0, destroyed = false;
    root.classList.add('vt-print');
    root.innerHTML = `<form class="vt-print-controls">
      <h1>Score print preview</h1><p>Print settings affect this preview only. Choose a printer or Save as PDF in the print dialog.</p>
      <fieldset data-print="tracks"><legend>Tracks</legend></fieldset>
      <div class="vt-print-options">
        <label>Notation <select name="notation"><option value="both">Staff and TAB</option><option value="staff">Staff</option><option value="tab">TAB</option></select></label>
        <label>Paper <select name="paper"><option value="a4">A4</option><option value="letter">Letter</option></select></label>
        <label>Orientation <select name="orientation"><option value="portrait">Portrait</option><option value="landscape">Landscape</option></select></label>
        <label>Scale (%) <input name="scale" type="number" min="40" max="150" value="80" required></label>
        <label>Top margin (mm) <input name="top" type="number" min="0" max="60" value="15" required></label>
        <label>Right margin (mm) <input name="right" type="number" min="0" max="60" value="15" required></label>
        <label>Bottom margin (mm) <input name="bottom" type="number" min="0" max="60" value="15" required></label>
        <label>Left margin (mm) <input name="left" type="number" min="0" max="60" value="15" required></label>
        <label>Title <input name="title" maxlength="200"></label><label>Subtitle <input name="subtitle" maxlength="200"></label>
        <label>Composer <input name="composer" maxlength="200"></label>
        <label>From bar <input name="first" type="number" min="1" value="1" required></label>
        <label>Through bar <input name="last" type="number" min="1" value="1" required></label>
        <label>Page breaks before <select name="breaks" multiple size="4" aria-describedby="vt-print-break-help"></select></label>
      </div>
      <p id="vt-print-break-help">Select bars to start on a new page (Ctrl/Command-click for several). Unmetered groups are display boundaries, not authored measures.</p>
      <button type="submit">Update preview</button> <button type="button" data-print="print" disabled>Print / Save PDF</button>
      <label>Image page <select name="imagePage" disabled></select></label>
      <button type="button" data-print="svg" disabled>Save page SVG</button>
      <button type="button" data-print="png" disabled>Save page PNG</button>
      <button type="button" data-print="jpg" disabled>Save page JPEG</button>
      <button type="button" data-print="bmp" disabled>Save page BMP</button>
      <p>PDF includes all preview pages. Images save the selected page; raster images use 192 pixels per inch. JPEG uses quality 95%; BMP is uncompressed.</p>
      <p data-print="summary"></p><p data-print="lyrics" role="status"></p>
    </form><p class="vt-print-status" role="status"></p><div class="vt-print-pages"></div><div class="vt-print-render" aria-hidden="true"></div>`;
    const form = root.querySelector('form'), field = name => form.elements.namedItem(name);
    const pages = root.querySelector('.vt-print-pages'), renderHost = root.querySelector('.vt-print-render');
    const status = root.querySelector('.vt-print-status'), printButton = root.querySelector('[data-print=print]');
    const imageButtons = ['svg', 'png', 'jpg', 'bmp'].map(type => root.querySelector(`[data-print=${type}]`));
    function imagesReady(ready) { for (const button of imageButtons) button.disabled = !ready || !saveImage; field('imagePage').disabled = !ready; }
    const pageStyle = document.createElement('style'); root.append(pageStyle);
    const credits = view.score?.metadata || {};
    field('title').value = credits.title ?? view.title ?? '';
    field('subtitle').value = [credits.artist, credits.album, credits.date, credits.transcriber && `Transcribed by ${credits.transcriber}`].filter(Boolean).join(' · ');
    field('composer').value = credits.author || '';
    let timeline, tracks;
    function failed(error) { printButton.disabled = true; imagesReady(false); pages.replaceChildren(); status.textContent = `Cannot print: ${error.message || error}`; }
    try {
      if (!Number.isInteger(previewChannel) || previewChannel < -2 || previewChannel >= view.channels.length) throw new Error('Invalid preview channel.');
      timeline = !view.native && !Object.keys(view.score?.tracks || {}).length ? trackerTimeline(view, previewChannel) : printTimeline(view);
      if (!timeline.ranges.length) throw new Error('This song has no ordered patterns to print.');
      tracks = timeline.tracks || view.score.tracks;
      for (const [id, spec] of Object.entries(tracks)) {
        const label = text('label', ''), input = document.createElement('input');
        input.type = 'checkbox'; input.name = 'track'; input.value = id; input.checked = true; label.append(input, document.createTextNode(spec.name || id));
        root.querySelector('[data-print=tracks]').append(label);
      }
      if (timeline.raw) { field('notation').value = 'staff'; field('notation').disabled = true; }
      field('first').max = field('last').max = field('last').value = timeline.ranges.length;
      timeline.ranges.forEach((r, i) => {
        if (!i) return;
        const option = text('option', `Bar ${i + 1} · ${r.authored ? r.id + ' · ' + r.meter.join('/') : 'unmetered group'} · ${r.from.join('/')} quarters`);
        option.value = i; field('breaks').append(option);
      });
      const raw = (view.raw_positions || []).length;
      root.querySelector('[data-print=summary]').textContent = timeline.raw ?
        `Tracker staff preview · ${timeline.occurrences.length} order occurrences · ${timeline.ranges.length} displayed bars · ${timeline.attacks} source notes · ${timeline.heads} noteheads. Row-grid rhythm; effects and sample tuning are not transcribed. The song is unchanged.` :
        `${view.orders.length} order occurrences · ${timeline.ranges.filter(r => r.authored).length} authored measures · ${timeline.ranges.length} displayed bars` +
        (timeline.ranges.some(r => !r.authored) ? ' · includes unmetered display groups' : '') +
        (raw ? ` · ${raw} unadopted Pattern note entries are not included` : '');
    } catch (error) { failed(error); }

    async function render() {
      const run = ++generation; printButton.disabled = true; imagesReady(false); pages.replaceChildren();
      api?.destroy(); api = null; renderHost.replaceChildren();
      if (!timeline || !form.reportValidity()) return;
      status.textContent = 'Rendering the full score…';
      try {
        const selected = [...form.querySelectorAll('input[name=track]:checked')].map(input => input.value);
        if (!selected.length) throw new Error('Choose at least one track.');
        const first = +field('first').value - 1, last = +field('last').value;
        if (first >= last) throw new Error('The first bar must not follow the last bar.');
        const ranges = timeline.ranges.slice(first, last);
        const dimensions = field('paper').value === 'letter' ? [215.9, 279.4] : [210, 297];
        if (field('orientation').value === 'landscape') dimensions.reverse();
        const [width, height] = dimensions, margins = ['top', 'right', 'bottom', 'left'].map(name => +field(name).value);
        const contentWidth = width - margins[1] - margins[3], contentHeight = height - margins[0] - Math.max(11, margins[2]);
        if (contentWidth < 60 || contentHeight < 60) throw new Error('Margins leave too little room for the score.');
        const breaks = new Set([...field('breaks').selectedOptions].map(o => +o.value - first).filter(i => i > 0 && i < ranges.length));
        renderHost.style.width = contentWidth + 'mm';
        pageStyle.textContent = `@page { size: ${width}mm ${height}mm; margin: 0; }`;
        root.style.setProperty('--vt-paper-width', width + 'mm'); root.style.setProperty('--vt-paper-height', height + 'mm');
        root.style.setProperty('--vt-paper-margins', margins.map(n => n + 'mm').join(' '));
        const current = api = new alphaTab.AlphaTabApi(renderHost, {
          core: {engine: 'svg', useWorkers: false, fontDirectory: '/web/', enableLazyLoading: false},
          display: {layoutMode: alphaTab.LayoutMode.Page, scale: +field('scale').value / 100, padding: [0, 0], effectBandPaddingBottom: 10},
          player: {playerMode: alphaTab.PlayerMode.Disabled, enableCursor: false, enableUserInteraction: false}
        });
        const score = notationScore(); score.title = field('title').value; score.subTitle = field('subtitle').value; score.music = field('composer').value;
        score.words = credits.writer || '';
        score.subTitle = [score.subTitle, credits.copyright].filter(Boolean).join(' · ');
        if (timeline.raw) {
          current.settings.display.resources.secondaryGlyphColor = current.settings.display.resources.mainGlyphColor;
          current.settings.notation.elements.set(alphaTab.NotationElement.EffectDynamics, false);
          score.subTitle = [score.subTitle, 'Tracker preview · row-grid rhythm; effects and sample tuning omitted'].filter(Boolean).join(' · ');
        }
        if (selected.length === 1) score.subTitle = [score.subTitle, tracks[selected[0]].name || selected[0]].filter(Boolean).join(' · ');
        if (first || last !== timeline.ranges.length)
          score.subTitle = [score.subTitle, `Source bars ${first + 1}–${last} (excerpt numbered from 1)`].filter(Boolean).join(' · ');
        document.title = score.title ? score.title + ' — Score print preview' : 'Score print preview';
        for (const id of selected) {
          const t = notationTrack(score, id, tracks[id], ranges, timeline.source.filter(b => b.track === id), timeline.tieTargets);
          const drums = isPercussion(tracks[id]);
          t.staves[0].showStandardNotation = drums || field('notation').value !== 'tab';
          t.staves[0].showTablature = !drums && field('notation').value !== 'staff';
          // alphaTab 1.8.4 uses the next bar's zero-based index as a system break.
          t.lineBreaks = new Set(breaks);
        }
        root.querySelector('[data-print=lyrics]').textContent = (view.lyrics?.errors || [])
          .filter(e => selected.includes(e.track)).map(e => e.message).join(' · ');
        if (!Number.isFinite(view.tempo) || view.tempo <= 0) throw new Error('The snapshot has no valid initial tempo.');
        if (timeline.raw) score.tempoUnitWarnings = []; // The preview does not transcribe tracker timing effects.
        else notationTempos(score, ranges, view);
        ranges.forEach((range, i) => {
          if (!timeline.raw && !range.authored && (i === 0 || ranges[i - 1].authored)) {
            const section = new alphaTab.model.Section(); section.text = 'Unmetered'; score.masterBars[i].section = section;
          }
        });
        const parts = new Map();
        current.renderer.preRender.on(() => parts.clear());
        current.renderer.partialRenderFinished.on(part => parts.set(part.id, part));
        current.error.on(error => { if (run === generation && !destroyed) failed(error); });
        current.postRenderFinished.on(async () => {
          try {
            await document.fonts.ready;
            if (destroyed || run !== generation) return;
            const layoutError = textLayoutError(current);
            if (layoutError) throw new Error(layoutError);
            pages.replaceChildren();
            const surfaceClass = renderHost.querySelector('.at-surface')?.className || 'at-surface';
            const maxHeight = contentHeight * 96 / 25.4, maxWidth = contentWidth * 96 / 25.4;
            let content = null, used = 0;
            const newPage = () => {
              const page = text('section', '', 'vt-print-page'); content = text('div', '', surfaceClass + ' vt-print-content');
              page.append(content); pages.append(page); used = 0;
            };
            for (const part of [...parts.values()].sort((a, b) => a.y - b.y)) {
              if (typeof part.renderResult !== 'string' || !part.renderResult) continue;
              const system = text('div', '', 'vt-print-part'); system.innerHTML = part.renderResult;
              system.dataset.firstBar = part.firstMasterBarIndex; system.dataset.lastBar = part.lastMasterBarIndex;
              if (!content || breaks.has(part.firstMasterBarIndex) && used > 0) newPage();
              content.append(system);
              const partHeight = system.getBoundingClientRect().height;
              if (system.scrollWidth > maxWidth + 1) throw new Error('A score system is wider than the page. Reduce scale or change paper settings.');
              if (partHeight > maxHeight + 1) throw new Error('A score system is taller than the page. Reduce scale, select fewer tracks or change paper settings.');
              if (used + partHeight > maxHeight + 0.1 && used > 0) { newPage(); content.append(system); }
              used += partHeight;
            }
            if (!pages.children.length) throw new Error('The renderer returned no printable score.');
            const actual = [...pages.querySelectorAll('.vt-print-part')].filter(el => +el.dataset.firstBar >= 0);
            let nextBar = 0;
            for (const system of actual) {
              if (+system.dataset.firstBar !== nextBar) throw new Error('The rendered score does not cover every bar.');
              nextBar = +system.dataset.lastBar + 1;
            }
            if (nextBar !== ranges.length) throw new Error('The rendered score does not cover every bar.');
            root.dataset.pages = pages.children.length;
            [...pages.children].forEach((page, index) => {
              const footer = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
              footer.classList.add('vt-print-footer'); footer.setAttribute('viewBox', '0 0 600 30');
              const label = document.createElementNS(footer.namespaceURI, 'text');
              label.setAttribute('x', '300'); label.setAttribute('y', '11'); label.setAttribute('text-anchor', 'middle');
              label.setAttribute('font-size', '10'); label.setAttribute('fill', '#333');
              const partName = selected.length === 1 ? tracks[selected[0]].name || selected[0] : 'Full score';
              label.textContent = `${score.title.slice(0, 65)} · ${partName.slice(0, 55)}`;
              const location = label.cloneNode(false), systems = [...page.querySelectorAll('.vt-print-part')].filter(el => +el.dataset.firstBar >= 0);
              const from = systems.length ? +systems[0].dataset.firstBar + first + 1 : null;
              const to = systems.length ? +systems.at(-1).dataset.lastBar + first + 1 : null;
              const sectionIndex = from == null ? -1 : timeline.ranges.slice(0, from).findLastIndex(range => range.marker?.title);
              const section = sectionIndex < 0 ? '' : `${timeline.ranges[sectionIndex].marker.title.slice(0, 65)}${sectionIndex < from - 1 ? ' (cont.)' : ''} · `;
              location.setAttribute('y', '25');
              location.textContent = `${section}${from == null ? 'Title' : from === to ? `Bar ${from}` : `Bars ${from}–${to}`} · ${index + 1} / ${pages.children.length}`;
              footer.append(label, location); page.append(footer);
              for (const line of [label, location]) if (line.getComputedTextLength() > 580) {
                line.setAttribute('textLength', '580'); line.setAttribute('lengthAdjust', 'spacingAndGlyphs');
              }
            });
            field('imagePage').replaceChildren(...[...pages.children].map((page, index) => {
              const option = text('option', `Page ${index + 1}`); option.value = index; return option;
            }));
            status.textContent = `${pages.children.length} page${pages.children.length === 1 ? '' : 's'} ready. Bars ${first + 1}–${last}. This preview is a snapshot; reopen it after song edits. ${score.tempoUnitWarnings.join(' ')}`.trim();
            printButton.disabled = false;
            imagesReady(true);
          } catch (error) { if (run === generation && !destroyed) failed(error); }
        });
        score.finish(current.settings); spaceChordDiagrams(current, score); current.renderScore(score, [-1]);
      } catch (error) { failed(error); }
    }
    const dataUrl = blob => new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob);
    });
    let musicFont, musicLicense;
    async function pageImage(format, index) {
      const page = pages.children[index];
      if (!page) throw new Error('Choose an available preview page.');
      await document.fonts.ready;
      const bounds = page.getBoundingClientRect(), ns = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(ns, 'svg');
      svg.setAttribute('width', root.style.getPropertyValue('--vt-paper-width'));
      svg.setAttribute('height', root.style.getPropertyValue('--vt-paper-height'));
      svg.setAttribute('viewBox', `0 0 ${bounds.width} ${bounds.height}`);
      if (!musicFont) {
        const [response, license] = await Promise.all([fetch('/web/Bravura.woff2'), fetch('/web/licenses/Bravura-OFL.txt')]);
        if (!response.ok || !license.ok) throw new Error('Could not embed the bundled music font and license.');
        musicLicense = await license.text();
        musicFont = await dataUrl(await response.blob());
      }
      const metadata = document.createElementNS(ns, 'metadata'); metadata.textContent = musicLicense; svg.append(metadata);
      const style = document.createElementNS(ns, 'style');
      style.textContent = `@font-face{font-family:VTExportMusic;src:url("${musicFont}") format("woff2");font-weight:normal;font-style:normal}`;
      svg.append(style);
      const background = document.createElementNS(ns, 'rect');
      background.setAttribute('width', '100%'); background.setAttribute('height', '100%'); background.setAttribute('fill', 'white'); svg.append(background);
      for (const original of page.querySelectorAll('.vt-print-part > svg, .vt-print-footer')) {
        const copy = original.cloneNode(true), box = original.getBoundingClientRect();
        const originals = [original, ...original.querySelectorAll('*')], copies = [copy, ...copy.querySelectorAll('*')];
        originals.forEach((element, i) => {
          const computed = getComputedStyle(element);
          for (const name of ['fill', 'fill-rule', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin',
            'font-family', 'font-size', 'font-style', 'font-weight', 'text-anchor', 'dominant-baseline', 'opacity'])
            copies[i].style.setProperty(name, computed.getPropertyValue(name));
          const music = element.closest('.at');
          if (music && original.contains(music)) copies[i].style.fontFamily = 'VTExportMusic';
        });
        copy.setAttribute('x', box.left - bounds.left); copy.setAttribute('y', box.top - bounds.top);
        copy.setAttribute('width', box.width); copy.setAttribute('height', box.height); svg.append(copy);
      }
      const blob = new Blob([new XMLSerializer().serializeToString(svg)], {type:'image/svg+xml'});
      if (format === 'svg') return (await dataUrl(blob)).split(',')[1];
      const image = new Image(), url = URL.createObjectURL(blob);
      try {
        await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = () => reject(new Error('Could not render the exported score image.')); image.src = url; });
        const canvas = document.createElement('canvas'); canvas.width = Math.round(bounds.width * 2); canvas.height = Math.round(bounds.height * 2);
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
        if (format === 'bmp') {
          // Windows BITMAPINFOHEADER, 24-bit BGR rows stored bottom-up with DWORD padding.
          const w=canvas.width,h=canvas.height,stride=(w*3+3)&~3,size=54+stride*h;
          if(size>24*1024*1024)throw new Error('BMP page exceeds 24 MiB; choose PNG or a smaller paper size.');
          const bytes=new Uint8Array(size),header=new DataView(bytes.buffer),pixels=canvas.getContext('2d').getImageData(0,0,w,h).data;
          bytes.set([0x42,0x4d]);header.setUint32(2,size,true);header.setUint32(10,54,true);header.setUint32(14,40,true);
          header.setInt32(18,w,true);header.setInt32(22,h,true);header.setUint16(26,1,true);header.setUint16(28,24,true);
          header.setUint32(34,stride*h,true);header.setInt32(38,7559,true);header.setInt32(42,7559,true);
          for(let y=0;y<h;y++)for(let x=0;x<w;x++){const from=(y*w+x)*4,to=54+(h-1-y)*stride+x*3;bytes[to]=pixels[from+2];bytes[to+1]=pixels[from+1];bytes[to+2]=pixels[from];}
          return (await dataUrl(new Blob([bytes],{type:'image/bmp'}))).split(',')[1];
        }
        return canvas.toDataURL(format==='jpg'?'image/jpeg':'image/png',.95).split(',')[1];
      } finally { URL.revokeObjectURL(url); }
    }
    for (const button of imageButtons) button.addEventListener('click', async () => {
      if (button.disabled) return;
      const run = generation, format = button.dataset.print, index = +field('imagePage').value;
      imagesReady(false); status.textContent = `Preparing page ${index + 1} ${format.toUpperCase()}…`;
      try {
        const data = await pageImage(format, index);
        if (destroyed || generation !== run) return;
        const result = await saveImage({song:view.song, revision:view.revision, format,
          name:(field('title').value || 'Score') + `-page-${index + 1}.${format}`, data});
        if (generation === run) status.textContent = result.path ? `Saved ${result.path}` : 'Image save cancelled. The preview is unchanged.';
      } catch (error) { if (generation === run) status.textContent = `Image export failed: ${error.message || error}`; }
      finally { if (!destroyed && generation === run) imagesReady(true); }
    }, {signal:abort.signal});
    form.addEventListener('submit', e => { e.preventDefault(); render(); }, {signal: abort.signal});
    form.addEventListener('input', event => {
      if (event.target.name === 'imagePage') return;
      generation++; printButton.disabled = true; imagesReady(false); pages.replaceChildren(); status.textContent = 'Update preview to apply these print settings.';
    }, {signal: abort.signal});
    printButton.addEventListener('click', () => { if (!printButton.disabled) window.print(); }, {signal: abort.signal});
    if (timeline) render();
    return {destroy() { destroyed = true; generation++; abort.abort(); api?.destroy(); root.replaceChildren(); root.classList.remove('vt-print'); }};
  }
  window.VultureTab = {mount, mountPrint};
  window.VultureTab.timeline = printTimeline; // ROLL's grid guides follow the same measures
})();
