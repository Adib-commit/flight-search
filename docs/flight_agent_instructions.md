# Project Instructions: AI Flight Optimization Application

You are an expert AI software engineer. Your task is to build a flight search and optimization application that accepts user-defined parameters and extracts the "best value" flight options based on a multi-metric scoring algorithm. 

Follow the structured instructions below to design, implement, and test the system.

---

## 1. Project Overview
The objective is to create a backend service (or CLI/lightweight web app) that interfaces with a flight data API, processes raw flight offers, filters them according to strict user constraints, and ranks them using a "Best Value" scoring mechanism (balancing price, duration, and convenience).

## 2. Input Parameter Specifications
The application must accept and validate the following input parameters:

* **Origin (`origin`):** IATA airport code (e.g., `JFK`, `LAX`, `LHR`) or city name.
* **Destination (`destination`):** IATA airport code or city name. *(Note: Necessary counterpart to origin for routing)*.
* **Dates of Flights (`flight_dates`):** * Departure Date (YYYY-MM-DD)
    * Return Date (YYYY-MM-DD, optional for one-way flights)
* **Number of Travelers (`traveler_count`):** Integer (Default: 1). Break down into adults/children if supported by the API.
* **Flight Type (`max_stops`):** * `Direct Only` (0 stops)
    * `Connections Allowed` (1+ stops)
* **Airline Preferences (`airline_filters`):**
    * `Include List`: Array of IATA airline codes allowed (exclude all others if populated).
    * `Exclude List`: Array of IATA airline codes strictly forbidden from results.

---

## 3. Tech Stack & Integration Guidance
* **Language:** Python 3.10+ or Node.js (TypeScript preferred).
* **Flight API Options:** Implement using one of the following reliable APIs:
    * **Amadeus Self-Service API** (Recommended: Flight Offers Search API)
    * **Skyscanner API** (via RapidAPI)
    * **SerpAPI / Google Flights API**
* **Configuration:** Use environment variables (`.env`) to store API keys and secrets securely. Do not hardcode credentials.

---

## 4. "Best Value" Scoring Algorithm Logic
Raw flight results should not just be sorted by price. Implement a weighted scoring system to determine the true **"Best Value"**. 

Calculate a score for each flight itinerary (lower score = better value):
$$\text{Score} = (\text{Normalized Price} \times W_p) + (\text{Normalized Duration} \times W_d) + (\text{Stop Penalty} \times W_s)$$

### Recommended Weights:
* Price Weight ($W_p$): **0.50** (50%)
* Duration Weight ($W_d$): **0.35** (35%)
* Stops Weight ($W_s$): **0.15** (15%)

### Logic Details:
1.  **Price:** Normalize prices relative to the cheapest option found in the dataset.
2.  **Duration:** Normalize total travel time (including layovers) relative to the fastest option found.
3.  **Stops Penalty:** Add a fixed penalty metric for each layover/connection (e.g., +50 points per stop).
4.  **Sorting:** Return the top 5 results with the lowest compiled score, labeled as "Best Value".

---

## 5. Step-by-Step AI Agent Implementation Workflow

### Step 1: Project Setup & Dependency Management
* Initialize the project directory structure.
* Create configuration files (`requirements.txt` or `package.json`).
* Set up an `.env` file template with placeholder keys for the chosen Flight API.

### Step 2: Data Validation Layer
* Create a robust parameter validation module (e.g., using `Pydantic` in Python).
* Ensure date parameters are in the future and departure dates precede return dates.
* Validate that IATA codes are valid 3-letter uppercase strings.

### Step 3: API Integration Client
* Build an asynchronous HTTP client wrapper to query the flight data API.
* Implement pagination processing if the API splits results across multiple pages.
* Transform the raw API response JSON into a clean, internal data structure (e.g., Object/Data Class containing price, carrier, stops, total duration, and segments).

### Step 4: Strict Filtering Engine
Apply post-fetch filters based on user criteria before running the optimization engine:
* **Stops Filter:** If `Direct Only` is selected, immediately discard any itinerary containing layovers.
* **Airline Include Filter:** If an inclusion list is provided, discard any itinerary containing a flight segment operated by an unlisted airline.
* **Airline Exclude Filter:** If an exclusion list is provided, discard any itinerary containing a flight segment operated by an excluded airline.

### Step 5: Optimization & Scoring Engine
* Implement the mathematical normalization functions for Price and Duration over the filtered dataset.
* Execute the calculation matrix for each valid itinerary.
* Sort the array in ascending order of final score.

### Step 6: Output Presentation
Provide the outputs in a clean structural layout. The app must output:
1.  **Top 3 "Best Value" Options** (Balanced price & speed)
2.  **Cheapest Option** (Absolute lowest cost)
3.  **Fastest Option** (Absolute lowest travel time)

Output formats should support JSON string extraction (for API usage) and a formatted Terminal/Markdown table text for human review.

---

## 6. Error Handling & Edge Cases
Ensure the agent builds protections for the following scenarios:
* **No Results Found:** Handle cases where strict airline filters leave zero options gracefully without crashing. Return a descriptive error message indicating which filter may be too restrictive.
* **API Rate Limits:** Implement a basic exponential backoff retry mechanism for API requests (`HTTP 429`).
* **Expired Dates:** Ensure validation prevents API token wastage on invalid historic dates.

---

## 7. Example Test Case Inputs
Use this example payload to verify the agent's code execution output correctness:

```json
{
  "origin": "JFK",
  "destination": "CDG",
  "flight_dates": {
    "departure": "2026-09-15",
    "return": "2026-09-22"
  },
  "traveler_count": 2,
  "max_stops": "Connections Allowed",
  "airline_filters": {
    "include": [],
    "exclude": ["Ryanair", "Spirit"]
  }
}