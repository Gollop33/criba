# TAREAS — qué chat usar para qué

> Este fichero existe para que **cada chat arranque sin tener que explicar nada**.
> Cuando abras uno nuevo, di: *"Lee TAREAS.md y sigue por donde toca."*

---

## 🔀 Cómo dividir los chats (y por qué ahorra)

El coste de un chat viene de **reenviar todo el historial en cada mensaje**. Así que
la regla es: **un chat = un tema**. Cuando el tema cambia, chat nuevo.

| Chat | Para qué | Skills | Comando antes de abrir |
|------|----------|:------:|------------------------|
| **A · Proyecto** | decisiones, estrategia, revisar estado, arreglar el bot | ❌ | `python sesion.py --charlar` |
| **B · Marketing** | SEO, redes, vídeos, copy, conversión | ✅ | `python sesion.py --marketing` |

**Por qué el interruptor:** DSH mete el catálogo de skills **entero** en cada petición.
Con las 14 activas son ~2.514 tokens por mensaje que pagas aunque estés hablando de
otra cosa. Apagarlas cuando no hacen falta es gratis.

⚠️ **El modo se aplica al ABRIR el chat.** Si cambias de modo con un chat abierto,
ese chat sigue con el catálogo que cargó. Cierra y abre.

---

## 🟢 Estado del sistema (a 2026-10-01)

```
Bot            : publicando, 104 envios el 30/09 (meta 150)
Fila           : 200 posts | 42 con cupon confirmado | 72 con pix real
Validacion     : 514 decisiones registradas en logs/validacion.jsonl
Token ML       : se renueva solo (duracion 6 h)
Pruebas        : 23/23 en probar_validador.py
Sitio          : 478 ofertas, SEO arreglado, sitemap + robots
Videos         : generador funcionando (video/generar_video.py)
```

---

## 📋 Pendientes, por chat

### Chat A · Proyecto

| # | Tarea | Estado |
|---|-------|--------|
| A1 | Verificar que el bot sigue publicando (runs de Actions) | ✅ sano |
| A2 | **Consumo de tokens**: revisar si otros procesos gastan de más | 🟡 abierto |
| A3 | Limpiar `video/toolchain/extraer_oferta.py` (lo dejó un agente que falló, sin usar) | ⏳ |
| A4 | Revisar `logs/validacion.jsonl` y ver si hay rechazos raros | ⏳ |

### Chat B · Marketing

| # | Tarea | Impacto | Estado |
|---|-------|---------|--------|
| B1 | **Vídeo "GRUPO"** — pantalla con ofertas cayendo (idea del usuario) | 🔥🔥 | diseñado, sin implementar |
| B2 | **Páginas por categoría** (`programmatic-seo`) — 12 páginas para Google | 🔥🔥🔥 | pendiente |
| B3 | **Alta en Google Search Console** — lo tiene que hacer el usuario | 🔥🔥🔥 | pendiente (10 min) |
| B4 | **Música en los vídeos** — ahora van mudos | 🔥 | pendiente |
| B5 | **Lote diario de vídeos** enganchado al workflow | 🔥 | pendiente |
| B6 | **3 datos de Meta** (FB + IG) — el código ya está listo | 🔥🔥 | pendiente (usuario) |
| B7 | Confirmar el diseño de los vídeos (colores, texto, tamaño) | — | esperando al usuario |

---

## 🎯 Lo que más rápido mueve la aguja

Por orden de impacto real:

1. **Google Search Console** (10 min tuyos) → sin esto Google no rastrea bien
2. **Páginas por categoría** (1 h mía) → tráfico gratis de Google
3. **Datos de Meta** (15 min tuyos) → publicar en Facebook e Instagram
4. **Vídeo GRUPO** (1 h mía) → contenido para TikTok/Reels
5. Resto

---

## 📚 Ficheros que importan

| Fichero | Qué es |
|---------|--------|
| `CONTEXT.md` | el documento maestro del proyecto |
| `.agents/product-marketing.md` | el contexto que leen las skills de marketing |
| `TAREAS.md` | este fichero |
| `video/README.md` | cómo funciona el generador de vídeos |
| `logs/validacion.jsonl` | cada decisión de validación, con su motivo |

---

## ⚠️ Reglas que NO se negocian

1. **Nunca inventar un dato.** Si no se puede verificar, no se publica. Ya costó caro:
   el bot publicó cupones que no aplicaban y un Pix que no existía, y el usuario lo
   descubrió **en el checkout real**.
2. **El cupón de afiliado no se pone.** El de ML se activa en la página, sin código.
   Ver `.agents/product-marketing.md`.
3. **Verificar con datos, no con "debería funcionar".** El precio se comprobó contra
   el checkout: el post decía R$ 1076 y ML cobró R$ 1.076,49.
4. **Al instalar skills, filtrar.** El catálogo se paga en cada mensaje, no una vez.
