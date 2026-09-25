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
- [ ] Agent + Tools

## Submission
- [ ] Short Description
- [ ] Long Description
- [ ] IBM Bob Usage Statement
- [ ] Video presentation
- [ ] Slide presentation
- [ ] Cover image

## Flow (Mermaid)
flowchart TD
    Start([Mulai])
    Selesai([Selesai])

    InputData[/Input: Terima Payload GitHub & Log/]
    OutputData[/Output: buat Docs dan taruh di codebasenya./]

    CheckFail{Apakah CI\nGagal?}
    Test100x[Jalankan Parallel Test Ulang 10x di Sandbox dengan pytest]
    CheckFlaky{Apakah Test\nFlaky?}
    ReadMode[READ Mode dari Agent untuk cari akar masalah]
    FilterDiff[Filter Git Diff mencari fungsi Async]
    CheckRoot1{Apakah akar masalah ketemu?}
    EkstrakAST[Ekstrak Struktur Kodingan AST]
    CheckRoot2{Apakah akar masalah ketemu?}
    CodeFixing[Code Fixing]
    Retest10x[Retest 10x]
    CheckPass{Apakah Pass\n100%?}

    Start --> InputData
    InputData --> CheckFail

    CheckFail -- Tidak --> Selesai
    CheckFail -- Ya --> Test100x

    Test100x --> CheckFlaky
    CheckFlaky -- Tidak --> Selesai
    CheckFlaky -- Ya --> ReadMode

    ReadMode --> FilterDiff
    FilterDiff --> CheckRoot1

    CheckRoot1 -- Yes --> CodeFixing
    CheckRoot1 -- No --> EkstrakAST

    EkstrakAST --> CheckRoot2
    CheckRoot2 -- Yes --> CodeFixing
    CheckRoot2 -- No --> Selesai

    CodeFixing --> Retest10x
    Retest10x --> CheckPass

    CheckPass -- Tidak --> Selesai
    CheckPass -- Ya --> OutputData
    OutputData --> Selesai