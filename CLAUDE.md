1. I want you to create an application that will get few parameters and get the best valuse for a flight according to the paramters i gave.
parameters are:
    * origin
    * dates of flights 
    * number of travelers 
    * connection or direct flights
    * include\exclude flight companies
2. Read the flight_agent_instructions md file and create a workplan to creathe this application locally
3. Update the application that the best score should be a combination of low cost and minumun stops or direct flights and minimum layovers
4. I want you to visualize he answer with the costs per a flight
5. I want a full list of all routes and the selected one in the visualization, flight times and layovers 
should be in hours not minuets
6. Add the option to have up to maximum price 
7. I need you to add a URL per each result to reviw the actual trip and to verify this
8. I need to display the airport name and not only IATA
9. I need you to add number of connections to the filter
10. I want to add a batch mode that i can activate. it should run every 1h and send notificatoion to an email address of the end user that it will get as a parameter when it finds a lower price. 
11. I want you to add  multi-day stopover section, an option that the connection can be in a different day at all. an example filght from TLV to bucharest at 04/08/2026, then  flight from bucharest to CLJ on the 06/08/2026 and back flight at 10/08/2026 from CLJ to bucharest and then at 11/08/2026 from bucharest to TLV
12. I want you to add multi scrappers kayak in addition to kiwi added skyscanner scrapper as well 
    The user wants the regular search to automatically detect possible multi-day split connections and show them in the results
*** Important  ***
example:
I searched and i didn't get multi day multi-day split connections for my results like wizz at 04/08/2026 from tlv to bucharest and from bucharest to cluj at 06/08/2026 and getting back from cluj to bucharest at 10/08/2026 and from bucharest to TLV at 11/04/2026 with wizz. CHECK THIS !!!

There is an issue with the Agent-built Multi-day Split-ticket via OTP. When the customer request up to 1 stop per direction means the the 4 LEGS ARE the stops 
  ! dont create in the boken legs more stops. change this - OR a flight with original connection or 4 different legs with direct flights
  
*** Important  ***

13. I want you to be able to activate multiple watchers and for stopover legs as well

You are an expert backend engineer and algorithm designer. Your task is to update the flight search engine in our application to implement a dynamic "Best Value" scoring and routing algorithm. 

Currently, the application supports multi-city searches (as shown in the reference image image_f5a9fd.png with a sample itinerary of TLV -> OTP -> CLJ -> OTP -> TLV for 5 travelers between 04/08/2026 and 11/08/2026). 

Please refactor the search engine and route-aggregator logic based on the following requirements:

### 1. Objective: "Best Value" Scoring Engine
Implement a scoring algorithm that ranks flight combinations not just by the cheapest price, but by a balance of cost, travel duration, and convenience. 
Define a `ValueScore` for each itinerary combination where a lower score equals better value. Use a heuristic formula similar to:

    ValueScore = (Total_Cost * Cost_Weight) + (Total_Stops * Stop_Penalty) + (Total_Layover_Hours * Layover_Weight)

Ensure the weights favor:
- Direct flights or minimum stops.
- Shorter, optimized layover windows (e.g., ideal layovers between 1.5 to 3 hours). 
- Heavy penalties for overnight layovers, risky short connections (< 1 hour), or excessively long dead time at airports.

### 2. Expanded Search Scope & Flexible Routing
- **Global Connections:** Do not limit multi-city segments strictly to point-to-point legs if a connection makes it significantly cheaper or faster. The system must evaluate connection/layover flights passing through *any* intermediate hub airport if it improves the overall `ValueScore`.
- **Date Boundary Enforcement:** The algorithm must search and evaluate all viable permutations across the entire specified date window (e.g., departing leg 1 on 04/08/2026 through the final leg on 11/08/2026), ensuring strict adherence to the traveler count (e.g., 5 travelers, Economy).

### 3. Output & Implementation Requirements
- Update the API search controller to sort results by this new `Best Value` metric by default, while still allowing users to toggle traditional "Cheapest" or "Fastest" sorts.
- Return a structured payload for each itinerary option showing:
  - Total Price
  - Total Travel Time
  - Breakdown of individual flight legs, stopovers (locations and durations), and their specific value deductions.

Review the existing flight aggregation code, implement the weighting logic mathematically, and ensure it seamlessly handles multi-city indexing.

Verify the application and create a workplan IF NEEDED to make it better 

*** Important ***


6. Create e2e tsts to verify the application is searching the web like https://www.skyscanner.com or other sites like https://www.wizzair.com/ or https://tequila.kiwi.com and getting original and right answers
    example for test:
    origin depart is from Tel-Aviv TLV to Cluj-Napoca (CLJ)
    an example can be:
    1. Dates are: 04/08/2026 to 11/08/2026 
    2. flight from TLV to Bucharest Otopeni (OTP) with Wizz at 04/08/2026
    3. flight from Bucharest Otopeni (OTP) to Cluj-Napoca (CLJ) with Wizz at 04/08/2026 
    4. flight from Cluj-Napoca (CLJ) to Bucharest Otopeni (OTP) with Wizz at 11/08/2026 
    5. flight from Bucharest Otopeni (OTP) to TLV with Wizz at 11/08/2026
    Sreach the web and verify this is the best value - less cost, minimum stops and less time or other connection sites are better