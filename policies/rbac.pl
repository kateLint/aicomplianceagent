% RBAC and Separation of Duties, evaluated at S8 and on officer decisions (T22-T24).
% Same semantics as src/reasoning/prolog_engine.py. Roles come from the employee
% directory (role/2), never from the form (anti-spoofing).

level(public, 0).  level(internal, 1).  level(confidential, 2).  level(restricted_pii, 3).

clearance(marketing, internal).
clearance(developer, confidential).
clearance(product_manager, confidential).
clearance(data_scientist, restricted_pii).
clearance(ciso, restricted_pii).
clearance(dpo, restricted_pii).

approver(ciso).  approver(dpo).

allowed_to_request(Person, Sensitivity) :-
    role(Person, Role), clearance(Role, Max),
    level(Sensitivity, L), level(Max, LMax), L =< LMax.

requires_dpo(Req) :- sensitivity(Req, restricted_pii).

can_decide(Officer, Req) :-
    role(Officer, Role), approver(Role),
    requester(Req, Requester), Officer \= Requester,
    ( requires_dpo(Req) -> Role == dpo ; true ).
