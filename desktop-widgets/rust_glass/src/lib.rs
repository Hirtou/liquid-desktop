//! Liquid Desktop — расчёт стекла на Rust (подключается из glass.py, numpy-версия остаётся запасной).
//!
//! Повторяет glass.py один в один (те же формулы, тот же порядок действий в f32):
//!   blur_lum — размытие уменьшенного снимка (три box-размытия ≈ гаусс, края — копия крайнего ряда) + яркость;
//!   tone     — цвет акрила: насыщенность и молочная/дымчатая подмесь;
//!   finish   — один проход вместо четырёх: середина + преломление у края + свет + оттенок темы + прозрачность.
//! Все функции отпускают GIL на время счёта: интерфейс не ждёт, пока считается стекло.

use numpy::ndarray::Array3;
use numpy::{IntoPyArray, PyArray3, PyReadonlyArray1, PyReadonlyArray3};
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

#[pymodule]
fn liquid_glass(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(blur_lum, m)?)?;
    m.add_function(wrap_pyfunction!(tone, m)?)?;
    m.add_function(wrap_pyfunction!(finish, m)?)?;
    m.add("VERSION", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
