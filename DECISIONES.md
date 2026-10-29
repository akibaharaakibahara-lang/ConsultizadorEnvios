# APIs del cotizador

El backend expone seis endpoints. La secuencia principal del formulario es:
guardar la solicitud (`POST /solicitudes-cotizacion`), consultar las tarifas
(`POST /cotizaciones`) y, si se necesita recuperar después el resultado,
consultar el historial (`GET /solicitudes-cotizacion/{solicitud_id}`).

## Decisión de diseño

Se separaron las APIs por responsabilidad para que cada operación tenga una
entrada y un resultado claros: verificar que el backend esté disponible,
resolver códigos postales, calcular una zona, registrar los datos del cliente,
consultar tarifas y recuperar el resultado guardado. Así se pueden probar y
reutilizar las operaciones sin mezclar el cálculo con el almacenamiento.

La decisión de consultar un servicio externo para los códigos postales evita
mantener manualmente una tabla local de localidades y coordenadas. El backend
convierte el resultado en coordenadas y calcula la distancia; la zona se
determina en el servidor para que el cliente no tenga que implementar ni poder
alterar las reglas de clasificación.

La solicitud se guarda antes de consultar las tarifas porque su ID permite
relacionar de forma persistente los datos ingresados con las opciones y
precios que se mostraron. De esa manera se puede consultar el historial
después, incluso si las tarifas cambian. El correo se solicita para
identificar la solicitud al recuperarla y evitar devolverla solo con un ID.

Se conserva `/distance` como operación independiente para consultar o probar
la distancia y la zona sin crear un registro. En cambio,
`POST /solicitudes-cotizacion` también calcula la zona internamente: no confía
en una zona enviada por el navegador y puede guardar una solicitud completa
en una sola operación.

El cálculo volumétrico pertenece a la consulta de cotizaciones porque afecta
qué rango de peso y tarifa se comparan por paquetería. Se controla mediante el
booleano y la fecha de vigencia de cada paquetería, en lugar de inferir la
regla por su nombre. Asociar la consulta mediante `solicitud_id` conserva el
precio seleccionado y el peso facturable exactos que recibió el usuario.

## Decisiones para la base de datos

Se separaron los datos en dos tablas porque representan cosas diferentes:

- **`solicitudes_cotizacion`** guarda una fila por solicitud del cliente:
  correo, códigos postales, peso, dimensiones, peso volumétrico, zona y fecha.
- **`cotizaciones`** guarda las opciones de paquetería calculadas para esa
  solicitud: precio, rango de peso, peso facturable y detalles de entrega.

La relación es de uno a varios: una solicitud puede tener varias opciones de
cotización. La tabla `cotizaciones` usa `solicitud_id` como referencia a
`solicitudes_cotizacion.id`. Así se evita repetir los datos del cliente y del
paquete en cada opción, y se puede recuperar todo el resultado de una
solicitud usando su ID.

Se guardan en `cotizaciones` los precios que se mostraron al cliente como una
instantánea del resultado. Si las tarifas cambian posteriormente, el historial
conserva el precio cotizado originalmente y no lo recalcula al consultar la
solicitud.

Las reglas de peso volumétrico se guardan por paquetería: `volumetrico`
indica si aplica y `volumetrico_desde` señala desde cuándo. Esto permite
activar la regla por configuración y vigencia, sin depender del nombre del
proveedor.

Las tarifas vigentes se mantienen en `tarifas`, separadas del historial de
cotizaciones. `tarifas` sirve para calcular nuevos precios; `cotizaciones`
conserva los precios ya presentados. Las cotizaciones históricas importadas
también se almacenan en `cotizaciones`, con una referencia histórica para
evitar insertar la misma referencia más de una vez.

Los cambios de precio se cargan como nuevas filas con `vigencia_desde`, sin
sobrescribir tarifas anteriores. El cotizador usa la versión más reciente que
ya esté vigente para el peso consultado; así las tarifas futuras no se aplican
antes de tiempo y las cotizaciones históricas permanecen intactas. Los archivos
con formato `tarifas_*_v*.csv` se importan automáticamente, por lo que un nuevo
archivo versionado no requiere modificar el código del importador.

## 1. Comprobar el estado del backend

**`GET /health`**

Indica si la API está disponible. Devuelve el estado y el nombre del servicio;
no consulta ni modifica datos de cotización.

Ejemplo de respuesta:

```json
{
  "status": "ok",
  "service": "V1 API"
}
```

## 2. Buscar un código postal

**`GET /postal-codes/{postal_code}`**

Consulta el código postal mexicano mediante el servicio externo Zippopotam.
Devuelve el código, localidad, estado y coordenadas geográficas. El código
debe tener exactamente cinco dígitos. Si no se encuentra o el proveedor no
está disponible, devuelve el error correspondiente.

Ejemplo: `GET /postal-codes/64000`

## 3. Calcular distancia y zona

**`POST /distance`**

Recibe los códigos postales de origen y destino, obtiene sus coordenadas y
calcula la distancia aproximada en kilómetros. Con esa distancia determina la
zona de tarifa:

- Zona 1: hasta 100 km.
- Zona 2: más de 100 y hasta 500 km.
- Zona 3: más de 500 y hasta 1,000 km.
- Zona 4: más de 1,000 km.

Ejemplo de solicitud:

```json
{
  "codigo_postal1": "64000",
  "codigo_postal2": "44100"
}
```

La respuesta contiene los datos de origen y destino, la distancia y la zona.
El endpoint calcula la zona, pero no guarda una solicitud.

## 4. Guardar una solicitud de cotización

**`POST /solicitudes-cotizacion`**

Registra en la base de datos el correo, los códigos postales, el peso y,
opcionalmente, las dimensiones del paquete. Calcula la distancia y la zona a
partir de los códigos postales y devuelve el identificador de la solicitud.
Cuando se incluyen las tres dimensiones calcula y guarda el peso volumétrico.

Ejemplo de solicitud:

```json
{
  "email": "cliente@ejemplo.com",
  "codigo_postal1": "64000",
  "codigo_postal2": "44100",
  "peso": 2,
  "largo": 20,
  "ancho": 40,
  "alto": 50
}
```

Las tres dimensiones deben enviarse juntas o dejarse todas vacías. El peso
debe ser mayor que cero. Este endpoint requiere `email`, `codigo_postal1`,
`codigo_postal2` y `peso`; mandar únicamente zona y dimensiones provoca un
error de validación.

## 5. Consultar tarifas de paqueterías

**`POST /cotizaciones`**

Busca las tarifas activas para una zona y un peso. Acepta dimensiones
opcionales y, si se proporciona, el `solicitud_id` para asociar a esa
solicitud las opciones y precios devueltos.

Ejemplo de solicitud:

```json
{
  "zona": 2,
  "peso": 2,
  "largo": 20,
  "ancho": 40,
  "alto": 50,
  "solicitud_id": 123
}
```

El peso volumétrico se calcula como `(largo × ancho × alto) / 5000`. Para cada
paquetería, el sistema aplica el cálculo volumétrico solo cuando su campo
booleano `volumetrico` está activado, hay dimensiones completas y ya se
alcanzó `volumetrico_desde` (si existe). En ese caso compara las tarifas
disponibles por peso real y volumétrico y devuelve la opción de mayor precio;
si no aplica, cotiza con el peso real. La respuesta incluye el precio, la
paquetería, el rango de peso y el peso facturable.

Si se envía `solicitud_id`, el endpoint comprueba que la solicitud exista y
que coincidan su zona, peso y dimensiones con la cotización. Después guarda
las opciones y los precios mostrados para poder consultarlos más tarde.

## 6. Recuperar una solicitud y sus cotizaciones

**`GET /solicitudes-cotizacion/{solicitud_id}?email={email}`**

Devuelve los datos guardados de una solicitud y las cotizaciones asociadas:
paqueterías, precios, pesos facturables y otros detalles disponibles. Se
requieren el ID de la solicitud y el correo usado al crearla. Si el ID no
existe o el correo no coincide, responde con `404`.

Ejemplo: `GET /solicitudes-cotizacion/123?email=cliente@ejemplo.com`

