//! Liquid Desktop — расчёт стекла на Rust (подключается из glass.py, numpy-версия остаётся запасной).
//!
//! Повторяет glass.py один в один (те же формулы, тот же порядок действий в f32):
//!   blur_lum — размытие уменьшенного снимка (три box-размытия ≈ гаусс, края — копия крайнего ряда) + яркость;
//!   tone     — цвет акрила: насыщенность и молочная/дымчатая подмесь;
//!   finish   — один проход вместо четырёх: середина + преломление у края + свет + оттенок темы + прозрачность;
//!   glow     — ореол темы (skins.glow_image): размытая кромка, затухание к краю, раскраска, premultiplied RGBA.
//! Все функции отпускают GIL на время счёта: интерфейс не ждёт, пока считается стекло.

use numpy::ndarray::Array3;
use numpy::{IntoPyArray, PyArray3, PyReadonlyArray1, PyReadonlyArray2, PyReadonlyArray3};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// box-размытие вдоль оси: как glass._box — накопленная сумма по ряду с краями-копиями, разность через 2r+1.
/// data — (rows, cols, 3) построчно; axis 0 — по строкам (вниз), 1 — по столбцам (вправо).
fn box_axis(src: &[f32], rows: usize, cols: usize, r: usize, axis: usize, out: &mut [f32], c: &mut Vec<f32>) {
    let (n, lines) = if axis == 0 { (rows, cols) } else { (cols, rows) };
    let win = (2 * r + 1) as f32;
    let len = n + 2 * r + 1;
    c.resize(len, 0.0);
    for line in 0..lines {
        for ch in 0..3 {
            let at = |i: usize| -> usize {
                if axis == 0 { (i * cols + line) * 3 + ch } else { (line * cols + i) * 3 + ch }
            };
            let first = src[at(0)];
            let last = src[at(n - 1)];
            // накопленная сумма ряда [first × (r+1), ряд, last × r] — по порядку, как np.cumsum (float32)
            let mut acc = 0.0f32;
            let mut k = 0;
            for _ in 0..(r + 1) {
                acc += first;
                c[k] = acc;
                k += 1;
            }
            for i in 0..n {
                acc += src[at(i)];
                c[k] = acc;
                k += 1;
            }
            for _ in 0..r {
                acc += last;
                c[k] = acc;
                k += 1;
            }
            for j in 0..n {
                out[at(j)] = (c[j + 2 * r + 1] - c[j]) / win;
            }
        }
    }
}

/// Размытие (src uint8 H×W×3 → float32 0..1) и средняя яркость (0.3R+0.59G+0.11B) — для выбора темы.
#[pyfunction]
fn blur_lum<'py>(py: Python<'py>, src: PyReadonlyArray3<'py, u8>, r: usize) -> PyResult<(Bound<'py, PyArray3<f32>>, f64)> {
    let a = src.as_array();
    let (h, w, ch) = a.dim();
    if ch != 3 || h == 0 || w == 0 {
        return Err(PyValueError::new_err("ожидается картинка H×W×3"));
    }
    let input: Vec<u8> = a.iter().copied().collect(); // по строкам, даже если массив не сплошной
    let (out, lum) = py.allow_threads(move || {
        let mut x: Vec<f32> = input.iter().map(|&v| v as f32 / 255.0).collect();
        let mut tmp = vec![0.0f32; x.len()];
        let mut c = Vec::new();
        for _ in 0..3 {
            box_axis(&x, h, w, r, 0, &mut tmp, &mut c);
            box_axis(&tmp, h, w, r, 1, &mut x, &mut c);
        }
        let mut s = 0.0f64;
        for px in x.chunks_exact(3) {
            s += (px[0] * 0.3 + px[1] * 0.59 + px[2] * 0.11) as f64;
        }
        (x, s / (h * w) as f64)
    });
    let arr = Array3::from_shape_vec((h, w, 3), out).map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok((arr.into_pyarray(py), lum))
}

/// Цвет акрила, как в glass.render: насыщенность вокруг серого, затем подмесь (тёмная дымка или молоко).
#[pyfunction]
fn tone<'py>(py: Python<'py>, small: PyReadonlyArray3<'py, f32>, dark: bool, k: f64, vivid: f64) -> PyResult<Bound<'py, PyArray3<u8>>> {
    let a = small.as_array();
    let (h, w, ch) = a.dim();
    if ch != 3 {
        return Err(PyValueError::new_err("ожидается картинка H×W×3"));
    }
    let input: Vec<f32> = a.iter().copied().collect();
    let out = py.allow_threads(move || {
        // числа — как их видит numpy: python float в паре с float32 считается во float32
        let (sat, mul) = if dark {
            ((0.5 + 0.6 * vivid) as f32, (0.8 + 0.15 * vivid) as f32)
        } else {
            ((1.15 + 0.35 * vivid) as f32, 1.0f32)
        };
        let base: [f32; 3] = if dark { [0.12, 0.12, 0.14] } else { [0.93, 0.93, 0.95] };
        let kf = k as f32;
        let keep = (1.0 - k) as f32;
        let add = [base[0] * kf, base[1] * kf, base[2] * kf];
        let mut out = vec![0u8; input.len()];
        for (px, o) in input.chunks_exact(3).zip(out.chunks_exact_mut(3)) {
            let gray = (px[0] + px[1] + px[2]) / 3.0;
            for i in 0..3 {
                let mut v = gray + (px[i] - gray) * sat;
                if dark {
                    v *= mul;
                }
                v = v * keep + add[i];
                o[i] = (v * 255.0).clamp(0.0, 255.0) as u8; // как np.clip(...).astype(uint8): отбросить дробь
            }
        }
        out
    });
    let arr = Array3::from_shape_vec((h, w, 3), out).map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(arr.into_pyarray(py))
}

/// Готовая картинка стекла RGBA (h×w×4) из увеличенной копии big (Hb×Wb×3), за один проход:
/// середина — пиксель big со сдвигом pad; полоса у края (band) — свой пиксель на каждый цвет (taps, преломление);
/// + свет (light); оттенок темы: rgb·m >> 6 + add (m < 0 — без оттенка; add — 3 числа или по пикселю);
/// прозрачность — маска скругления (alpha), с заливкой fill % — пропорционально.
#[pyfunction]
#[pyo3(signature = (big, w, h, pad, band, tap_r, tap_g, tap_b, light, alpha, fill=None, tint_m=-1, tint_add=None))]
#[allow(clippy::too_many_arguments)]
fn finish<'py>(
    py: Python<'py>,
    big: PyReadonlyArray3<'py, u8>,
    w: usize,
    h: usize,
    pad: usize,
    band: PyReadonlyArray1<'py, i64>,
    tap_r: PyReadonlyArray1<'py, i32>,
    tap_g: PyReadonlyArray1<'py, i32>,
    tap_b: PyReadonlyArray1<'py, i32>,
    light: PyReadonlyArray1<'py, i16>,
    alpha: PyReadonlyArray1<'py, u8>,
    fill: Option<f64>,
    tint_m: i32,
    tint_add: Option<PyReadonlyArray1<'py, i16>>,
) -> PyResult<Bound<'py, PyArray3<u8>>> {
    let bv = big.as_array();
    let (hb, wb, ch) = bv.dim();
    if ch != 3 || hb < h + pad || wb < w + pad {
        return Err(PyValueError::new_err("big меньше карточки"));
    }
    let n = w * h;
    let bigv: Vec<u8> = bv.iter().copied().collect();
    let band = band.as_slice()?.to_vec();
    let taps = [tap_r.as_slice()?.to_vec(), tap_g.as_slice()?.to_vec(), tap_b.as_slice()?.to_vec()];
    let light = light.as_slice()?.to_vec();
    let alpha = alpha.as_slice()?.to_vec();
    if light.len() != n || alpha.len() != n || taps.iter().any(|t| t.len() != band.len()) {
        return Err(PyValueError::new_err("размеры геометрии не совпадают с карточкой"));
    }
    let add: Option<Vec<i16>> = match tint_add {
        Some(a) => Some(a.as_slice()?.to_vec()),
        None => None,
    };
    if let Some(a) = &add {
        if a.len() != 3 && a.len() != n * 3 {
            return Err(PyValueError::new_err("оттенок: нужно 3 числа или по пикселю"));
        }
    }
    let lim = (hb * wb) as i64;
    if band.iter().any(|&b| b < 0 || b as usize >= n) || taps.iter().flatten().any(|&t| t < 0 || t as i64 >= lim) {
        return Err(PyValueError::new_err("индексы полосы вне картинки"));
    }
    let out = py.allow_threads(move || {
        let mut rgb = vec![0i16; n * 3];
        for y in 0..h {
            let row = ((y + pad) * wb + pad) * 3;
            for x in 0..w {
                let s = row + x * 3;
                let d = (y * w + x) * 3;
                rgb[d] = bigv[s] as i16;
                rgb[d + 1] = bigv[s + 1] as i16;
                rgb[d + 2] = bigv[s + 2] as i16;
            }
        }
        for (j, &b) in band.iter().enumerate() {
            let d = b as usize * 3;
            for c in 0..3 {
                rgb[d + c] = bigv[taps[c][j] as usize * 3 + c] as i16;
            }
        }
        let mut out = vec![0u8; n * 4];
        let fillf = fill.map(|f| f as f32);
        for i in 0..n {
            for c in 0..3 {
                let mut v = rgb[i * 3 + c].wrapping_add(light[i]);
                if tint_m >= 0 {
                    // как numpy с int16: умножение по модулю, сдвиг арифметический
                    v = v.wrapping_mul(tint_m as i16) >> 6;
                    if let Some(a) = &add {
                        v = v.wrapping_add(if a.len() == 3 { a[c] } else { a[i * 3 + c] });
                    }
                }
                out[i * 4 + c] = v.clamp(0, 255) as u8;
            }
            out[i * 4 + 3] = match fillf {
                None => alpha[i],
                Some(f) => (alpha[i] as f32 * f / 100.0) as u8,
            };
        }
        out
    });
    let arr = Array3::from_shape_vec((h, w, 4), out).map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(arr.into_pyarray(py))
}

/// Мягкое размытие маски, как skins._soft: края — нули (не копия!), накопленная сумма в f32, разность через 2r+1.
/// Обе оси идут по памяти подряд: по столбцам (axis 0) накопленные суммы — целыми строками (тот же порядок
/// сложений в каждом столбце, что у np.cumsum, — числа те же), по строкам (axis 1) — внутри строки.
fn soft_axis(a: &[f32], rows: usize, cols: usize, r: usize, axis: usize, out: &mut [f32], c: &mut Vec<f32>) {
    let d = (2 * r + 1) as f32;
    if axis == 0 {
        let n = rows;
        let total = n + 2 * r + 1;
        c.clear();
        c.resize(total * cols, 0.0);
        for k in 0..total {
            let i = k as isize - (r as isize + 1);
            let (prev, cur) = if k == 0 { (None, 0) } else { (Some((k - 1) * cols), k * cols) };
            for x in 0..cols {
                let v = if i >= 0 && (i as usize) < n { a[i as usize * cols + x] } else { 0.0 };
                c[cur + x] = match prev { Some(pr) => c[pr + x] + v, None => v };
            }
        }
        for i in 0..n {
            let (hi, lo) = ((i + 2 * r + 1) * cols, i * cols);
            for x in 0..cols {
                out[i * cols + x] = (c[hi + x] - c[lo + x]) / d;
            }
        }
    } else {
        let n = cols;
        c.clear();
        c.resize(n + 2 * r + 1, 0.0);
        for line in 0..rows {
            let row = &a[line * cols..(line + 1) * cols];
            let mut acc = 0.0f32;
            for k in 0..(n + 2 * r + 1) {
                let i = k as isize - (r as isize + 1);
                if i >= 0 && (i as usize) < n {
                    acc += row[i as usize];
                } else {
                    acc += 0.0;
                }
                c[k] = acc;
            }
            for i in 0..n {
                out[line * cols + i] = (c[i + 2 * r + 1] - c[i]) / d;
            }
        }
    }
}

const POW_N: usize = 65536;

/// x^0.8 таблицей (65 537 точек, между ними — прямая): powf из libm на каждый пиксель был главным расходом glow.
/// Отличие от точного — меньше 1e-5, на яркости 0..255 не видно.
fn pow08() -> &'static [f32] {
    static LUT: std::sync::OnceLock<Vec<f32>> = std::sync::OnceLock::new();
    LUT.get_or_init(|| (0..=POW_N).map(|i| ((i as f64) / POW_N as f64).powf(0.8) as f32).collect())
}

fn smooth(x: f32) -> f32 {
    let x = ((x - 0.3) / 0.4).clamp(0.0, 1.0);
    x * x * (3.0 - 2.0 * x)
}

/// Ореол темы: маска кромки (u8) -> размытие -> нормировка, ^0.8, сила -> затухание к краю картинки ->
/// не заходит внутрь формы -> цвет. kind: 0 — сверху вниз двумя цветами (Неон), 1 — слева/справа, 2 — сверху/снизу,
/// 3 — крест (своя тема: у неё цвет несёт и прозрачность). bx..bh — где форма на картинке (для 1–3).
#[pyfunction]
#[pyo3(signature = (mask, inside, r, strength, fade_w, kind, colors, bx, by, bw, bh))]
#[allow(clippy::too_many_arguments)]
fn glow<'py>(
    py: Python<'py>, mask: PyReadonlyArray2<'py, u8>, inside: PyReadonlyArray2<'py, u8>, r: usize, strength: f32,
    fade_w: f32, kind: u8, colors: PyReadonlyArray2<'py, f32>, bx: f32, by: f32, bw: f32, bh: f32,
) -> PyResult<Bound<'py, PyArray3<u8>>> {
    let m = mask.as_array();
    let (h, w) = m.dim();
    if inside.as_array().dim() != (h, w) || h == 0 || w == 0 {
        return Err(PyValueError::new_err("маски разного размера"));
    }
    let cols_arr = colors.as_array();
    let need = if kind == 3 { 4 } else { 2 };
    if cols_arr.dim().0 < need || cols_arr.dim().1 != 4 {
        return Err(PyValueError::new_err("мало цветов свечения"));
    }
    let pal: Vec<[f32; 4]> = (0..cols_arr.dim().0)
        .map(|i| [cols_arr[[i, 0]], cols_arr[[i, 1]], cols_arr[[i, 2]], cols_arr[[i, 3]]])
        .collect();
    let mk: Vec<u8> = m.iter().copied().collect();
    let ins: Vec<u8> = inside.as_array().iter().copied().collect();
    let out = py.allow_threads(move || {
        let mut a: Vec<f32> = mk.iter().map(|&v| v as f32 / 255.0).collect();
        let mut tmp = vec![0.0f32; a.len()];
        let mut c = Vec::new();
        for _ in 0..3 {
            soft_axis(&a, h, w, r, 0, &mut tmp, &mut c);
            soft_axis(&tmp, h, w, r, 1, &mut a, &mut c);
        }
        let mx = a.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        let mx = (mx as f64).max(1e-6) as f32;
        let lut = pow08();
        for v in a.iter_mut() {
            let x = (*v / mx).clamp(0.0, 1.0) * POW_N as f32;
            let i = (x as usize).min(POW_N - 1);
            let f = x - i as f32;
            *v = (lut[i] + (lut[i + 1] - lut[i]) * f) * strength;
        }
        if fade_w > 0.0 {
            for y in 0..h {
                let ey = (y.min(h - 1 - y)) as f32 + 0.5;
                for x in 0..w {
                    let ex = (x.min(w - 1 - x)) as f32 + 0.5;
                    let f = (ey.min(ex) / fade_w).clamp(0.0, 1.0);
                    a[y * w + x] *= f * f * (3.0 - 2.0 * f);
                }
            }
        }
        for (v, &i) in a.iter_mut().zip(ins.iter()) {
            *v *= 1.0 - i as f32 / 255.0;
        }
        let mut out = vec![0u8; h * w * 4];
        let fx: Vec<f32> = (0..w).map(|x| (x as f32 + 0.5 - bx) / bw).collect();
        let fy: Vec<f32> = (0..h).map(|y| (y as f32 + 0.5 - by) / bh).collect();
        for y in 0..h {
            let t_row = if h > 1 { (y as f64 / (h - 1) as f64) as f32 } else { 0.0 };
            for x in 0..w {
                let mut al = a[y * w + x];
                let col: [f32; 3];
                match kind {
                    0 => {
                        let (c0, c1) = (pal[0], pal[1]);
                        col = [c0[0] * (1.0 - t_row) + c1[0] * t_row, c0[1] * (1.0 - t_row) + c1[1] * t_row,
                               c0[2] * (1.0 - t_row) + c1[2] * t_row];
                    }
                    1 | 2 => {
                        let t = if kind == 1 { smooth(fx[x]) } else { smooth(fy[y]) };
                        let mut cc = [0.0f32; 4];
                        for k in 0..4 {
                            cc[k] = pal[0][k] * (1.0 - t) + pal[1][k] * t;
                        }
                        col = [cc[0], cc[1], cc[2]];
                        al *= cc[3];
                    }
                    _ => {
                        // cos(угол − сторона) без тригонометрии: угол = atan2(ys, xs), значит cos = xs/r, sin = ys/r;
                        // стороны −π/2, 0, π/2, π дают −sin, cos, sin, −cos (в точке 0,0 — угол 0, как у atan2)
                        let ys = fy[y] * 2.0 - 1.0;
                        let xs = fx[x] * 2.0 - 1.0;
                        let rr = (xs * xs + ys * ys).sqrt();
                        let (cs, sn) = if rr > 0.0 { (xs / rr, ys / rr) } else { (1.0, 0.0) };
                        let mut wsum = 0.0f32;
                        let mut wts = [0.0f32; 4];
                        for (i, v) in [-sn, cs, sn, -cs].iter().enumerate() {
                            wts[i] = v.max(0.0).powi(3);
                            wsum += wts[i];
                        }
                        wsum += 1e-6;
                        let mut cc = [0.0f32; 4];
                        for k in 0..4 {
                            let mut s = 0.0f32;
                            for i in 0..4 {
                                s += wts[i] * pal[i][k];
                            }
                            cc[k] = s / wsum;
                        }
                        col = [cc[0], cc[1], cc[2]];
                        al *= cc[3];
                    }
                }
                let o = (y * w + x) * 4;
                for k in 0..3 {
                    out[o + k] = (col[k] * al) as u8; // как присвоение float -> uint8 в numpy (дробь отбрасывается)
                }
                out[o + 3] = (al * 255.0) as u8;
            }
        }
        out
    });
    let arr = Array3::from_shape_vec((h, w, 4), out).map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(arr.into_pyarray(py))
}


#[pymodule]
fn liquid_glass(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(blur_lum, m)?)?;
    m.add_function(wrap_pyfunction!(tone, m)?)?;
    m.add_function(wrap_pyfunction!(finish, m)?)?;
    m.add_function(wrap_pyfunction!(glow, m)?)?;
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
