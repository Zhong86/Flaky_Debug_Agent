# Flaky Debug Agent

A CI/CD automation system that debugs flaky-based deployments. 
External system that relies on Github Actions. 
The goal of the system is to determine if the failure is a flaky-based error. 
If it is not then call Bob for fixing instantly. 
Else run through check test for possible root causes in the Git Diffs then Modularity of the feature.

## Todo
- [ ] Handle deploy.yml
- [ ] Endpoint utk dihit + callback
- [ ] LangGraph
- [ ] Monitoring dashboard
- [ ] Agent + Tools


## Submission
- [ ] Short Description
- [ ] Long Description
- [ ] IBM Bob Usage Statement
- [ ] Video presentation
- [ ] Slide presentation
- [ ] Cover image

## Flow (Mermaid)
```mermaid
flowchart TD
    Start([Start])
    End([End])

    InputData[/Input: Receive GitHub Payload & Logs/]
    OutputData[/Output: Generate Docs and place them in the codebase/]

    CheckFail{Did CI\nFail?}
    Test100x[Run Parallel Retest 10x in Sandbox with pytest]
    CheckFlaky{Is the Test\nFlaky?}
    MultiAgent[Multi-Agent System]
    CodeFixing[Code Fixing]
    Retest10x[Retest 10x]
    CheckPass{Does it Pass\n100%?}

    Start --> InputData
    InputData --> CheckFail

    CheckFail -- No --> End
    CheckFail -- Yes --> Test100x

    Test100x --> CheckFlaky
    CheckFlaky -- No --> End
    CheckFlaky -- Yes --> MultiAgent

    MultiAgent --> CodeFixing
    CodeFixing --> Retest10x
    Retest10x --> CheckPass

    CheckPass -- No --> End
    CheckPass -- Yes --> OutputData
    OutputData --> End