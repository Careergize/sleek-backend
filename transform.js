const fs = require("fs")

// =========================
// READ FILE
// =========================

const content = fs.readFileSync("cars.js", "utf-8")

// =========================
// IMAGE IMPORT MAPPING
// =========================

const imageMap = {}

const importRegex =
    /import\s+(\w+)\s+from\s+["'].*\/([^/]+\.(jpg|png|jpeg|webp))["']/g

let match

while ((match = importRegex.exec(content)) !== null) {

    const variable = match[1]

    const filename = match[2]

    imageMap[variable] = `/media/cars/${filename}`
}

// =========================
// REMOVE IMPORTS
// =========================

let cleaned = content.replace(/^import.*$/gm, "")

// =========================
// FIND fleetCars ARRAY
// =========================

const startIndex = cleaned.indexOf("export const fleetCars")

if (startIndex === -1) {

    console.log("fleetCars not found")

    process.exit(1)
}

// =========================
// EXTRACT ARRAY
// =========================

const arrayStart = cleaned.indexOf("[", startIndex)

let arrayEnd = -1
let bracketCount = 0
for (let i = arrayStart; i < cleaned.length; i++) {
    if (cleaned[i] === "[") bracketCount++
    else if (cleaned[i] === "]") bracketCount--

    if (bracketCount === 0) {
        arrayEnd = i
        break
    }
}

const arrayText = cleaned.substring(
    arrayStart,
    arrayEnd + 1
)

// =========================
// CONVERT TO OBJECT
// =========================

// Define image variables in global scope to prevent ReferenceError during eval
for (const variable in imageMap) {
    global[variable] = variable
}

const fleetCars = eval("(" + arrayText + ")")

// =========================
// TRANSFORM
// =========================

const transformed = fleetCars.map(car => ({

    id: car.id,

    brand: car.brand,

    name: car.name,

    category: car.category,

    image: imageMap[car.image] || null,

    price_day: car.priceDay,

    price_week: car.priceWeek,

    price_month: car.priceMonth,

    mileage_limit: car.mileageLimit,

    additional_mileage: car.additionalMileage,

    min_rental: car.minRental,

    location: car.location,

    specs: car.specs,

    overview: car.overview,

    features: car.features,

    description: car.description

}))

// =========================
// SAVE OUTPUT
// =========================

const output =
    "export const djangoCars = " +
    JSON.stringify(transformed, null, 4)

fs.writeFileSync(
    "django_cars.js",
    output
)

console.log("django_cars.js created successfully")