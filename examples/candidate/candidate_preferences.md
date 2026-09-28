# Personal preferences in job selection

Free-form notes read by the JD analyzer. Each section below feeds the field
named in its heading. Rewrite them for yourself -- the model follows what you
write here, so be as specific as you want.

### Salary (field: salary_match)
 - Balance location against income: rent, commuting and travel costs all count.
    - Use max_salary as the reference for every comparison. Return True for the conditions below.
    - Within 70 km of Lisbon: max_salary of EUR 55000 and above
    - Porto: max_salary >= EUR 60000
    - Anywhere else in Portugal: max_salary >= EUR 65000
    - Madrid, Barcelona, London: max_salary >= EUR 80000
    - Any other European location: max_salary > EUR 100000
 - Anything else: False

### Personal preference (field: pers_preference_score)
 - Job location within 60 km of Lisbon: 1.5 points
 - Hybrid job in Porto or Madrid: 1 point
 - Fully remote job: 0.5 points
 - The job requires speaking Spanish or working with Spanish-speaking teams: 1 point
 - The company operates in Latin America or is a Spanish company: 1 point
 - Well-known international company: 0.5 points
 - Innovative work on AI infrastructure or on large-scale event platforms: 0.5 points
 - Leading a team or owning a platform (Head of Platform, Engineering Manager): 1 point

### Should apply (fields: should_apply, should_apply_reason)
Strict rules -- check them in this order; the first one that matches decides:
 1. max_salary is stated (not -1) and max_salary < 50000, or match_percentage < 60: NO
 2. salary_match is false and (pers_preference_score < 3 or match_percentage < 65): NO
 3. salary_match is true and match_percentage > 70 and company_name is one of Contoso, Fabrikam, Tailspin, Globex: CHECK
 4. salary_match is true and match_percentage > 80: YES
 5. salary_match is true and match_percentage > 75 and pers_preference_score > 2.5: YES
 6. salary_match is not specified and match_percentage > 75 and pers_preference_score > 2.5: CHECK
 
Judgement rules -- only for a job that no strict rule above matched:
 - Reject any job unfit for the candidate (NO): the candidate misses a core
   requirement of the role, e.g. the position is for an SAP Basis administrator
   or for a "VP of Engineering with 10+ years managing managers". The missing
   competence must be core: listed as mandatory in a visible spot in the first
   part of the JD.
 - Weigh the job as a whole: if it has strong winning points but falls slightly
   short on one (e.g. a famous company and a good salary but a somewhat low
   match, or a high-match role whose salary is about 5k short), mark it CHECK.
 - Reject every remaining case: NO.
